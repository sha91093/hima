"""
地番正規化・展開エンジン

手入力された不規則な地番文字列を、SISで使える正規形に変換する。
主な機能:
  - 文字の正規化（全角→半角、漢数字→算用数字、不要語削除）
  - セパレーターによる分割
  - 枝番補完ロジック（"1-1,2,3" → ["1-1", "1-2", "1-3"]）
  - 大字の分離
"""

import re
import unicodedata


# --- 漢数字変換テーブル ---
_KANJI_DIGIT = {
    "〇": "0", "零": "0",
    "一": "1", "壱": "1",
    "二": "2", "弐": "2",
    "三": "3", "参": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}

_KANJI_UNIT = {
    "十": 10,
    "百": 100,
    "千": 1000,
}

# --- 削除対象キーワード ---
DEFAULT_REMOVE_KEYWORDS = [
    "借り", "借", "作", "所有", "付近",
    "の一部", "一部", "ほか", "他", "等",
    "地内", "地先",
]


def kanji_number_to_int(text: str) -> int | None:
    """
    漢数字の文字列を整数に変換する。
    例: "二十三" → 23, "百五" → 105
    単純な漢数字のみ対応（万以上は非対応）。
    変換できない場合は None を返す。
    """
    if not text:
        return None

    # 全文字が漢数字・単位かチェック
    valid_chars = set(_KANJI_DIGIT.keys()) | set(_KANJI_UNIT.keys())
    if not all(c in valid_chars for c in text):
        return None

    result = 0
    current = 0

    for ch in text:
        if ch in _KANJI_DIGIT:
            current = int(_KANJI_DIGIT[ch])
        elif ch in _KANJI_UNIT:
            unit = _KANJI_UNIT[ch]
            if current == 0:
                current = 1
            result += current * unit
            current = 0

    result += current
    return result


def normalize_characters(text: str, convert_kanji: bool = True) -> str:
    """
    文字列の基本正規化。
    - 全角英数字・記号 → 半角
    - 全角スペース → 削除
    - 全角ハイフン系 → 半角ハイフン
    - 漢数字の単独数値 → 算用数字（convert_kanji=True時のみ）
    """
    if not isinstance(text, str):
        return str(text) if text is not None else ""

    # NFKC正規化（全角英数字→半角など）
    text = unicodedata.normalize("NFKC", text)

    # 全角スペース削除
    text = text.replace("\u3000", "")

    # 各種ハイフン・ダッシュを統一
    hyphens = ["ー", "－", "‐", "‑", "–", "—", "―", "−"]
    for h in hyphens:
        text = text.replace(h, "-")

    # 先頭・末尾の空白除去
    text = text.strip()

    # 漢数字を算用数字に変換（地番中に混在するケース）
    if convert_kanji:
        text = _replace_kanji_numbers_in_text(text)

    return text


def _replace_kanji_numbers_in_text(text: str) -> str:
    """
    テキスト中の漢数字部分を算用数字に置換する。
    大字名の漢字（例: "三本木"）を壊さないよう、
    漢数字のみで構成される連続部分だけ変換する。
    """
    kanji_num_chars = set(_KANJI_DIGIT.keys()) | set(_KANJI_UNIT.keys())

    # 漢数字文字の連続をマッチさせるパターン
    pattern_chars = "".join(re.escape(c) for c in kanji_num_chars)
    pattern = re.compile(f"[{pattern_chars}]+")

    def _replace(m: re.Match) -> str:
        matched = m.group()
        converted = kanji_number_to_int(matched)
        if converted is not None:
            return str(converted)
        return matched

    return pattern.sub(_replace, text)


def remove_keywords(text: str, keywords: list[str] | None = None) -> str:
    """
    事務的に不要なキーワードを削除する。
    例: "123-1 借り" → "123-1"
    """
    if keywords is None:
        keywords = DEFAULT_REMOVE_KEYWORDS

    # 「、外3筆」のようなパターン（キーワード削除の前に実行）
    text = re.sub(r"[、,]?\s*外\d+筆", "", text)
    # 末尾の「外」（"123-1 外" や "123-1、外"）
    text = re.sub(r"[、,]?\s*外\s*$", "", text)

    for kw in keywords:
        text = text.replace(kw, "")

    # 残った余計なスペースを整理
    text = re.sub(r"\s+", " ", text).strip()

    return text


def split_by_separators(text: str) -> list[str]:
    """
    カンマ・読点・中黒・スペースなどのセパレーターで分割する。
    """
    # 「、」「，」「,」「・」「/」「　」で分割
    parts = re.split(r"[、，,・/\s]+", text)
    return [p.strip() for p in parts if p.strip()]


def expand_branch_numbers(parts: list[str]) -> list[str]:
    """
    枝番補完ロジック。
    先頭の要素が「親番-枝番」形式の場合、後続の単独数字を同じ親番で補完する。

    例:
      ["1-1", "2", "3"] → ["1-1", "1-2", "1-3"]
      ["100-1-ア", "イ"] → ["100-1-ア", "100-1-イ"]
      ["5", "6", "7"] → ["5", "6", "7"]  (親番なしはそのまま)
    """
    if not parts:
        return []

    result = []
    current_parent = None  # 現在の親番部分 (例: "1")
    current_depth = 0  # ハイフンの深さ

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            # ハイフンを含む → 新しい親番を設定
            result.append(part)
            segments = part.split("-")
            # 親番は最後のセグメント以外
            current_parent = "-".join(segments[:-1])
            current_depth = len(segments) - 1
        elif current_parent is not None and _is_simple_value(part):
            # 単独の数字またはカナ → 親番を補完
            result.append(f"{current_parent}-{part}")
        else:
            # 親番がない or 複雑な値 → そのまま
            result.append(part)

    return result


def _is_simple_value(text: str) -> bool:
    """枝番として補完可能な単純な値かどうか判定。"""
    # 数字のみ
    if re.fullmatch(r"\d+", text):
        return True
    # カタカナ1文字（ア、イ、ウ...）
    if re.fullmatch(r"[ア-ン]", text):
        return True
    # ひらがな1文字
    if re.fullmatch(r"[あ-ん]", text):
        return True
    # アルファベット1文字
    if re.fullmatch(r"[a-zA-Z]", text):
        return True
    return False


def _looks_like_chiban(text: str) -> bool:
    """分割後の要素が地番らしいかどうか判定する。人名等を除外するため。"""
    # 数字で始まる（例: "1618-1", "123", "1618-1-イ"）
    if re.match(r"\d", text):
        return True
    # 枝番補完で使える単純な値（カナ1文字等）
    if _is_simple_value(text):
        return True
    return False


def extract_oaza(text: str, oaza_list: list[str]) -> tuple[str, str]:
    """
    大字名を前方一致で分離する。

    Args:
        text: 正規化済みの地番文字列（例: "三本木123-1"）
        oaza_list: SISマスターの大字名リスト

    Returns:
        (大字名, 地番部分) のタプル。
        大字が見つからなければ ("", text) を返す。
    """
    # 長い大字名から優先的にマッチさせる
    sorted_oaza = sorted(oaza_list, key=len, reverse=True)

    for oaza in sorted_oaza:
        if text.startswith(oaza):
            remainder = text[len(oaza):].strip()
            return oaza, remainder

    return "", text


def normalize_single(raw: str, oaza_list: list[str] | None = None,
                     extra_keywords: list[str] | None = None) -> list[dict]:
    """
    1つのセル値を正規化し、展開された地番のリストを返す。

    Args:
        raw: Excelセルの生の値
        oaza_list: 大字名リスト（Noneなら大字分離しない）
        extra_keywords: 追加の削除キーワード

    Returns:
        各地番の辞書リスト:
        [{"oaza": "三本木", "chiban": "123-1", "full": "三本木123-1", "raw": "..."}]
    """
    if not raw or (isinstance(raw, float) and str(raw) == "nan"):
        return []

    raw_str = str(raw).strip()
    if not raw_str:
        return []

    # ステップ1: 文字正規化（漢数字はまだ変換しない＝大字名を壊さないため）
    text = normalize_characters(raw_str, convert_kanji=False)

    # ステップ2: 不要キーワード削除
    keywords = DEFAULT_REMOVE_KEYWORDS[:]
    if extra_keywords:
        keywords.extend(extra_keywords)
    text = remove_keywords(text, keywords)

    if not text:
        return []

    # ステップ3: 大字分離（漢数字変換前なので「三本木」等がそのまま一致する）
    oaza = ""
    parcel_text = text
    if oaza_list:
        oaza, parcel_text = extract_oaza(text, oaza_list)

    # ステップ3.5: 小字名（字○○）を除去
    # 例: "字吉富 1618-1" → "1618-1"
    parcel_text = re.sub(r"字[^\d\s\-,、・/ア-ンa-zA-Z]+", "", parcel_text)
    parcel_text = parcel_text.strip()

    # ステップ3.6: 地番部分のみ漢数字→算用数字に変換
    parcel_text = _replace_kanji_numbers_in_text(parcel_text)

    if not parcel_text:
        return []

    # ステップ3.7: 数字の直後にカタカナが続く場合、ハイフンを挿入
    # 例: "200-1ア" → "200-1-ア"（分筆カナ表記の補完）
    parcel_text = re.sub(r"(\d)([ア-ン])", r"\1-\2", parcel_text)

    # ステップ3.8: 「数字の数字」→「数字-数字」（古い地番表記の変換）
    parcel_text = re.sub(r"(\d)の(\d)", r"\1-\2", parcel_text)

    # ステップ3.9: 地番として不要な日本語テキスト（説明文）を除去
    # "の加藤の田んぼ" のような非地番テキストを末尾から除去
    parcel_text = re.sub(r"[のにでがをへは][^\d\-,、・/ア-ンa-zA-Z].*$", "",
                         parcel_text)

    # ステップ4: セパレーター分割
    parts = split_by_separators(parcel_text)

    # ステップ4.5: 地番らしくない要素（人名等）を除去
    # 数字・ハイフン・カナ1文字で始まるもののみ残す
    parts = [p for p in parts if _looks_like_chiban(p)]

    # ステップ5: 枝番補完
    expanded = expand_branch_numbers(parts)

    # 結果を組み立て
    results = []
    for chiban in expanded:
        # 地番として不正な文字を含まないかチェック
        chiban = chiban.strip()
        if not chiban:
            continue
        full = f"{oaza}{chiban}" if oaza else chiban
        results.append({
            "oaza": oaza,
            "chiban": chiban,
            "full": full,
            "raw": raw_str,
        })

    return results


def normalize_batch(raw_values: list[str],
                    oaza_list: list[str] | None = None,
                    extra_keywords: list[str] | None = None) -> list[dict]:
    """
    複数のセル値を一括正規化する。

    Returns:
        各地番の辞書リスト。"row_index" フィールドで元の行番号を追跡。
    """
    all_results = []
    for idx, raw in enumerate(raw_values):
        parcels = normalize_single(raw, oaza_list, extra_keywords)
        for p in parcels:
            p["row_index"] = idx
            all_results.append(p)
    return all_results
