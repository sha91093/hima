"""
SIS突合ロジック

正規化した地番をSISマスターデータと照合し、
一致・推測成功・判定不能の3段階で判定する。
"""

import re
from difflib import SequenceMatcher
from enum import Enum

from .normalizer import normalize_characters


class MatchStatus(Enum):
    """突合ステータス"""
    EXACT = "exact"         # 完全一致
    INFERRED = "inferred"   # 推測成功（枝番展開等で一致）
    UNMATCHED = "unmatched" # 判定不能


class SISMatcher:
    """SISマスターデータとの突合を行うクラス。"""

    def __init__(self, master_parcels: set[str], oaza_list: list[str] | None = None):
        """
        Args:
            master_parcels: SISの正解地番のセット
            oaza_list: 大字名リスト
        """
        self.master_parcels = master_parcels
        self.oaza_list = oaza_list or []

        # 検索用インデックスを構築
        self._normalized_index: dict[str, str] = {}
        for p in master_parcels:
            key = self._make_key(p)
            self._normalized_index[key] = p

        # 大字ごとの地番インデックス
        self._by_oaza: dict[str, list[str]] = {}
        for p in master_parcels:
            for oaza in self.oaza_list:
                if p.startswith(oaza):
                    self._by_oaza.setdefault(oaza, []).append(p)
                    break
            else:
                self._by_oaza.setdefault("", []).append(p)

    def _make_key(self, text: str) -> str:
        """正規化したキーを作成（スペース・ハイフン統一）。"""
        key = normalize_characters(text)
        # スペース除去
        key = re.sub(r"\s+", "", key)
        return key

    def match_single(self, normalized_parcel: dict) -> dict:
        """
        正規化済みの1地番をマスターと照合する。

        Args:
            normalized_parcel: normalizer.normalize_single の出力要素
                {"oaza": "...", "chiban": "...", "full": "...", "raw": "..."}

        Returns:
            {
                "input": normalized_parcel,
                "status": MatchStatus,
                "matched_to": マッチしたマスター地番 or None,
                "candidates": 類似候補リスト（判定不能時）,
                "confidence": 信頼度 (0.0-1.0),
            }
        """
        full = normalized_parcel["full"]
        key = self._make_key(full)

        # 1. 完全一致チェック
        if full in self.master_parcels:
            return {
                "input": normalized_parcel,
                "status": MatchStatus.EXACT,
                "matched_to": full,
                "candidates": [],
                "confidence": 1.0,
            }

        # 2. 正規化キーでの一致（スペースやハイフンの違いを吸収）
        if key in self._normalized_index:
            return {
                "input": normalized_parcel,
                "status": MatchStatus.INFERRED,
                "matched_to": self._normalized_index[key],
                "candidates": [],
                "confidence": 0.95,
            }

        # 3. 大字+地番で部分一致を試みる
        oaza = normalized_parcel.get("oaza", "")
        chiban = normalized_parcel.get("chiban", "")

        # 大字が分かっている場合、その大字の地番のみ検索
        search_pool = self._by_oaza.get(oaza, []) if oaza else list(self.master_parcels)

        # 地番部分だけで一致するか
        for master_p in search_pool:
            if oaza and master_p.startswith(oaza):
                master_chiban = master_p[len(oaza):]
            else:
                master_chiban = master_p

            if self._make_key(chiban) == self._make_key(master_chiban):
                return {
                    "input": normalized_parcel,
                    "status": MatchStatus.INFERRED,
                    "matched_to": master_p,
                    "candidates": [],
                    "confidence": 0.85,
                }

        # 4. あいまい検索（類似度が高い候補を返す）
        candidates = self._find_similar(full, search_pool, max_candidates=5)

        if candidates and candidates[0]["score"] >= 0.8:
            return {
                "input": normalized_parcel,
                "status": MatchStatus.INFERRED,
                "matched_to": candidates[0]["parcel"],
                "candidates": candidates,
                "confidence": candidates[0]["score"],
            }

        return {
            "input": normalized_parcel,
            "status": MatchStatus.UNMATCHED,
            "matched_to": None,
            "candidates": candidates,
            "confidence": 0.0,
        }

    def match_batch(self, normalized_parcels: list[dict]) -> list[dict]:
        """複数の正規化済み地番を一括照合する。"""
        return [self.match_single(p) for p in normalized_parcels]

    def _find_similar(self, query: str, pool: list[str],
                      max_candidates: int = 5) -> list[dict]:
        """あいまい検索で類似候補を返す。"""
        scored = []
        query_key = self._make_key(query)

        for p in pool:
            p_key = self._make_key(p)
            score = SequenceMatcher(None, query_key, p_key).ratio()
            if score > 0.4:
                scored.append({"parcel": p, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_candidates]

    def search_master(self, query: str, max_results: int = 20) -> list[str]:
        """
        マスターデータをキーワード検索する（GUI用）。
        """
        query = query.strip()
        if not query:
            return []

        results = []
        for p in sorted(self.master_parcels):
            if query in p:
                results.append(p)
                if len(results) >= max_results:
                    break

        return results

    def get_statistics(self, match_results: list[dict]) -> dict:
        """突合結果の統計情報を返す。"""
        total = len(match_results)
        exact = sum(1 for r in match_results if r["status"] == MatchStatus.EXACT)
        inferred = sum(1 for r in match_results if r["status"] == MatchStatus.INFERRED)
        unmatched = sum(1 for r in match_results if r["status"] == MatchStatus.UNMATCHED)

        return {
            "total": total,
            "exact": exact,
            "inferred": inferred,
            "unmatched": unmatched,
            "exact_rate": exact / total * 100 if total else 0,
            "resolved_rate": (exact + inferred) / total * 100 if total else 0,
        }
