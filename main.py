#!/usr/bin/env python3
"""
地番名寄せシステム - メインエントリポイント

使い方:
    python main.py          → GUI起動
    python main.py --cli    → CLIモード（テスト・デバッグ用）
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="地番名寄せシステム")
    parser.add_argument("--cli", action="store_true",
                        help="CLIモードで動作（GUIなし）")
    parser.add_argument("--input", "-i", type=str,
                        help="入力Excel/CSVファイルパス")
    parser.add_argument("--master", "-m", type=str,
                        help="SISマスターCSVファイルパス")
    parser.add_argument("--output", "-o", type=str,
                        help="出力CSVファイルパス")
    parser.add_argument("--chiban-col", type=str, default="0",
                        help="入力ファイルの地番列（列番号 or 列名）")
    parser.add_argument("--master-chiban-col", type=str, default="0",
                        help="マスターの地番列")
    parser.add_argument("--master-oaza-col", type=str, default=None,
                        help="マスターの大字列")
    args = parser.parse_args()

    if args.cli:
        _run_cli(args)
    else:
        _run_gui()


def _run_gui():
    """GUIモードで起動。"""
    from land_parcel_normalizer.gui import LandParcelApp
    app = LandParcelApp()
    app.run()


def _run_cli(args):
    """CLIモードで変換を実行。"""
    from land_parcel_normalizer.normalizer import normalize_single
    from land_parcel_normalizer.converter import (
        read_csv_column, read_master_csv, convert_and_compare,
        export_comparison_csv,
    )
    from land_parcel_normalizer.matcher import SISMatcher

    try:
        import pandas as pd
        from land_parcel_normalizer.converter import read_excel_column
        has_pandas = True
    except ImportError:
        has_pandas = False

    if not args.input:
        # 対話的テストモード
        print("=== 地番正規化テストモード ===")
        print("地番文字列を入力してください（終了: Ctrl+C）:")
        while True:
            try:
                raw = input("> ")
                results = normalize_single(raw)
                for r in results:
                    print(f"  → {r['full']}")
                if not results:
                    print("  → (変換結果なし)")
            except (KeyboardInterrupt, EOFError):
                print("\n終了")
                break
        return

    # ファイル処理モード
    input_path = args.input

    # 列番号パース
    def parse_col(val):
        if val is None:
            return None
        return int(val) if val.isdigit() else val

    chiban_col = parse_col(args.chiban_col)

    # 入力読み込み
    if input_path.lower().endswith((".xlsx", ".xls")):
        if not has_pandas:
            print("エラー: Excel読み込みにはpandasが必要です。", file=sys.stderr)
            sys.exit(1)
        input_rows = read_excel_column(input_path, chiban_column=chiban_col)
    else:
        input_rows = read_csv_column(input_path, chiban_column=chiban_col)

    print(f"入力: {len(input_rows)}行読み込み")

    # マスター読み込み
    oaza_list = None
    matcher = None
    if args.master:
        master_chiban_col = parse_col(args.master_chiban_col)
        master_oaza_col = parse_col(args.master_oaza_col)
        master_data = read_master_csv(
            args.master,
            chiban_column=master_chiban_col,
            oaza_column=master_oaza_col,
        )
        oaza_list = master_data["oaza_list"]
        matcher = SISMatcher(master_data["parcels"], oaza_list)
        print(f"マスター: {len(master_data['parcels'])}件の正解地番")

    # 変換
    comparison = convert_and_compare(input_rows, oaza_list=oaza_list)

    # 突合
    if matcher:
        all_match_results = []
        for comp in comparison:
            for parcel in comp["normalized"]:
                result = matcher.match_single(parcel)
                all_match_results.append(result)

        stats = matcher.get_statistics(all_match_results)
        print(f"\n--- 突合結果 ---")
        print(f"合計:     {stats['total']}件")
        print(f"完全一致: {stats['exact']}件 ({stats['exact_rate']:.1f}%)")
        print(f"推測成功: {stats['inferred']}件")
        print(f"判定不能: {stats['unmatched']}件")
        print(f"解決率:   {stats['resolved_rate']:.1f}%")

    # 出力
    if args.output:
        export_comparison_csv(comparison, args.output)
        print(f"\n結果を保存しました: {args.output}")
    else:
        print(f"\n--- 変換結果（先頭20件） ---")
        for comp in comparison[:20]:
            print(f"  {comp['raw']}")
            print(f"    → {comp['normalized_text']}")


if __name__ == "__main__":
    main()
