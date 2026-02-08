"""
Excel読み込み・変換・比較表出力パイプライン

現場管理Excelの地番列を読み込み、正規化処理を行い、
「変換前・変換後」の比較表をExcel/CSVで出力する。
"""

import csv
from pathlib import Path

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from .normalizer import normalize_single, normalize_batch


def read_excel_column(filepath: str, sheet_name: str | int = 0,
                      chiban_column: str | int = 0,
                      header_row: int = 0) -> list[dict]:
    """
    Excelファイルから地番列を読み込む。

    Args:
        filepath: Excelファイルパス
        sheet_name: シート名またはインデックス
        chiban_column: 地番が入っている列名またはインデックス
        header_row: ヘッダー行（0始まり）

    Returns:
        [{"row": 行番号, "raw": 生の値, "other_columns": {他の列データ}}]
    """
    if not HAS_PANDAS:
        raise ImportError(
            "pandasがインストールされていません。\n"
            "pip install pandas openpyxl を実行してください。"
        )

    df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row)

    # 列の特定
    if isinstance(chiban_column, int):
        col_name = df.columns[chiban_column]
    else:
        col_name = chiban_column

    rows = []
    for idx, row in df.iterrows():
        raw_value = row[col_name]
        other_cols = {c: row[c] for c in df.columns if c != col_name}
        rows.append({
            "row": idx,
            "raw": str(raw_value) if pd.notna(raw_value) else "",
            "other_columns": other_cols,
        })

    return rows


def read_csv_column(filepath: str, chiban_column: str | int = 0,
                    encoding: str = "cp932") -> list[dict]:
    """
    CSVファイルから地番列を読み込む。
    日本語環境のCSVはcp932(Shift-JIS)が多いためデフォルトで指定。
    読み込みに失敗した場合はUTF-8等で再試行する。
    """
    encodings_to_try = [encoding, "utf-8", "utf-8-sig", "cp932"]
    # 重複除去しつつ順序保持
    seen = set()
    unique_encodings = []
    for enc in encodings_to_try:
        if enc not in seen:
            unique_encodings.append(enc)
            seen.add(enc)

    for enc in unique_encodings:
        try:
            rows = []
            with open(filepath, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []

                if isinstance(chiban_column, int):
                    col_name = fieldnames[chiban_column]
                else:
                    col_name = chiban_column

                for idx, row_data in enumerate(reader):
                    raw_value = row_data.get(col_name, "")
                    other_cols = {c: row_data[c] for c in fieldnames
                                  if c != col_name}
                    rows.append({
                        "row": idx,
                        "raw": raw_value,
                        "other_columns": other_cols,
                    })

            return rows
        except (UnicodeDecodeError, UnicodeError):
            continue

    raise ValueError(
        f"ファイル {filepath} を読み込めませんでした。"
        f"エンコーディングを確認してください。"
    )


def read_master_csv(filepath: str, chiban_column: str | int = 0,
                    oaza_column: str | int | None = None,
                    encoding: str = "cp932") -> dict:
    """
    SISマスター（正解地番CSV）を読み込む。

    Returns:
        {
            "parcels": set of 正解地番文字列,
            "oaza_list": list of 大字名,
            "raw_records": list of 元レコード,
        }
    """
    parcels = set()
    oaza_set = set()
    raw_records = []

    encodings_to_try = [encoding, "utf-8", "cp932", "utf-8-sig"]

    for enc in encodings_to_try:
        try:
            with open(filepath, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []

                if isinstance(chiban_column, int):
                    chiban_col_name = fieldnames[chiban_column]
                else:
                    chiban_col_name = chiban_column

                oaza_col_name = None
                if oaza_column is not None:
                    if isinstance(oaza_column, int):
                        oaza_col_name = fieldnames[oaza_column]
                    else:
                        oaza_col_name = oaza_column

                for row_data in reader:
                    chiban = row_data.get(chiban_col_name, "").strip()
                    if chiban:
                        parcels.add(chiban)
                        raw_records.append(row_data)

                    if oaza_col_name:
                        oaza = row_data.get(oaza_col_name, "").strip()
                        if oaza:
                            oaza_set.add(oaza)

            break  # 成功したらループ抜ける
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(
            f"ファイル {filepath} を読み込めませんでした。"
            f"エンコーディングを確認してください。"
        )

    return {
        "parcels": parcels,
        "oaza_list": sorted(oaza_set),
        "raw_records": raw_records,
    }


def convert_and_compare(input_rows: list[dict],
                        oaza_list: list[str] | None = None,
                        extra_keywords: list[str] | None = None) -> list[dict]:
    """
    入力行を正規化し、変換前・変換後の比較リストを作成する。

    Returns:
        [{"row": 行番号,
          "raw": 変換前,
          "normalized": [変換後の地番リスト],
          "normalized_text": 変換後をカンマ区切りにした文字列,
          "count": 展開された地番数,
          "other_columns": {他の列}}]
    """
    results = []

    for row_data in input_rows:
        raw = row_data["raw"]
        parcels = normalize_single(raw, oaza_list, extra_keywords)

        normalized_list = [p["full"] for p in parcels]
        results.append({
            "row": row_data["row"],
            "raw": raw,
            "normalized": parcels,
            "normalized_text": ", ".join(normalized_list),
            "count": len(normalized_list),
            "other_columns": row_data.get("other_columns", {}),
        })

    return results


def export_comparison_excel(results: list[dict], output_path: str,
                            include_other_columns: bool = True) -> None:
    """
    比較結果をExcelファイルに出力する。
    """
    if not HAS_PANDAS:
        raise ImportError("pandasが必要です。pip install pandas openpyxl")

    rows_for_df = []
    for r in results:
        row = {
            "元の行番号": r["row"],
            "変換前（原文）": r["raw"],
            "変換後": r["normalized_text"],
            "展開数": r["count"],
        }
        if include_other_columns:
            for col, val in r.get("other_columns", {}).items():
                row[f"[元]{col}"] = val
        rows_for_df.append(row)

    df = pd.DataFrame(rows_for_df)
    df.to_excel(output_path, index=False, engine="openpyxl")


def export_comparison_csv(results: list[dict], output_path: str,
                          encoding: str = "cp932") -> None:
    """
    比較結果をCSVファイルに出力する。
    """
    fieldnames = ["元の行番号", "変換前（原文）", "変換後", "展開数"]

    # 他の列名を集める
    other_cols = set()
    for r in results:
        other_cols.update(r.get("other_columns", {}).keys())
    other_col_names = sorted(other_cols)
    fieldnames.extend(f"[元]{c}" for c in other_col_names)

    with open(output_path, "w", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            row = {
                "元の行番号": r["row"],
                "変換前（原文）": r["raw"],
                "変換後": r["normalized_text"],
                "展開数": r["count"],
            }
            for col in other_col_names:
                row[f"[元]{col}"] = r.get("other_columns", {}).get(col, "")
            writer.writerow(row)
