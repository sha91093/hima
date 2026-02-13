"""地番正規化エンジンのテスト"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from land_parcel_normalizer.normalizer import (
    kanji_number_to_int,
    normalize_characters,
    remove_keywords,
    split_by_separators,
    expand_branch_numbers,
    extract_oaza,
    normalize_single,
)


class TestKanjiNumber(unittest.TestCase):
    """漢数字変換のテスト"""

    def test_single_digit(self):
        self.assertEqual(kanji_number_to_int("一"), 1)
        self.assertEqual(kanji_number_to_int("九"), 9)
        self.assertEqual(kanji_number_to_int("〇"), 0)

    def test_tens(self):
        self.assertEqual(kanji_number_to_int("十"), 10)
        self.assertEqual(kanji_number_to_int("二十三"), 23)
        self.assertEqual(kanji_number_to_int("十五"), 15)

    def test_hundreds(self):
        self.assertEqual(kanji_number_to_int("百"), 100)
        self.assertEqual(kanji_number_to_int("百二十五"), 125)
        self.assertEqual(kanji_number_to_int("三百"), 300)

    def test_invalid(self):
        self.assertIsNone(kanji_number_to_int(""))
        self.assertIsNone(kanji_number_to_int("あいう"))
        self.assertIsNone(kanji_number_to_int("三本木"))


class TestNormalizeCharacters(unittest.TestCase):
    """文字正規化のテスト"""

    def test_fullwidth_digits(self):
        self.assertEqual(normalize_characters("１２３"), "123")

    def test_fullwidth_hyphen(self):
        self.assertEqual(normalize_characters("１２３ー１"), "123-1")
        self.assertEqual(normalize_characters("１２３－１"), "123-1")

    def test_fullwidth_space(self):
        self.assertEqual(normalize_characters("１２３　１"), "123 1")

    def test_kanji_numbers(self):
        result = normalize_characters("百二十三")
        self.assertEqual(result, "123")

    def test_mixed(self):
        result = normalize_characters("１２３−１")
        self.assertEqual(result, "123-1")


class TestRemoveKeywords(unittest.TestCase):
    """不要キーワード削除のテスト"""

    def test_basic(self):
        self.assertEqual(remove_keywords("123-1 借り"), "123-1")
        self.assertEqual(remove_keywords("123-1 作"), "123-1")
        self.assertEqual(remove_keywords("123-1 所有"), "123-1")

    def test_gai(self):
        self.assertEqual(remove_keywords("123-1、外"), "123-1")

    def test_multiple_hitsu(self):
        self.assertEqual(remove_keywords("123-1 外3筆"), "123-1")


class TestSplitBySeparators(unittest.TestCase):
    """セパレーター分割のテスト"""

    def test_comma(self):
        self.assertEqual(split_by_separators("1,2,3"), ["1", "2", "3"])

    def test_toten(self):
        self.assertEqual(split_by_separators("1、2、3"), ["1", "2", "3"])

    def test_nakaguro(self):
        self.assertEqual(split_by_separators("ア・イ・ウ"), ["ア", "イ", "ウ"])

    def test_mixed(self):
        parts = split_by_separators("1-1、2,3")
        self.assertEqual(parts, ["1-1", "2", "3"])


class TestExpandBranchNumbers(unittest.TestCase):
    """枝番補完のテスト"""

    def test_basic_expansion(self):
        result = expand_branch_numbers(["1-1", "2", "3"])
        self.assertEqual(result, ["1-1", "1-2", "1-3"])

    def test_no_expansion_needed(self):
        result = expand_branch_numbers(["1-1", "1-2", "1-3"])
        self.assertEqual(result, ["1-1", "1-2", "1-3"])

    def test_kana_expansion(self):
        result = expand_branch_numbers(["200-1-ア", "イ", "ウ"])
        self.assertEqual(result, ["200-1-ア", "200-1-イ", "200-1-ウ"])

    def test_no_parent(self):
        result = expand_branch_numbers(["5", "6", "7"])
        self.assertEqual(result, ["5", "6", "7"])

    def test_empty(self):
        self.assertEqual(expand_branch_numbers([]), [])


class TestExtractOaza(unittest.TestCase):
    """大字分離のテスト"""

    def test_found(self):
        oaza_list = ["三本木", "大平沢"]
        oaza, chiban = extract_oaza("三本木123-1", oaza_list)
        self.assertEqual(oaza, "三本木")
        self.assertEqual(chiban, "123-1")

    def test_not_found(self):
        oaza_list = ["三本木", "大平沢"]
        oaza, chiban = extract_oaza("123-1", oaza_list)
        self.assertEqual(oaza, "")
        self.assertEqual(chiban, "123-1")

    def test_longer_match_priority(self):
        oaza_list = ["大平", "大平沢"]
        oaza, chiban = extract_oaza("大平沢123", oaza_list)
        self.assertEqual(oaza, "大平沢")
        self.assertEqual(chiban, "123")


class TestNormalizeSingle(unittest.TestCase):
    """統合正規化のテスト"""

    def test_basic(self):
        results = normalize_single("１２３−１、２、３")
        fulls = [r["full"] for r in results]
        self.assertEqual(fulls, ["123-1", "123-2", "123-3"])

    def test_with_oaza(self):
        oaza_list = ["三本木"]
        results = normalize_single("三本木123-1", oaza_list)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["oaza"], "三本木")
        self.assertEqual(results[0]["chiban"], "123-1")
        self.assertEqual(results[0]["full"], "三本木123-1")

    def test_with_keyword_removal(self):
        results = normalize_single("１２３−１ 借り")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full"], "123-1")

    def test_empty(self):
        self.assertEqual(normalize_single(""), [])
        self.assertEqual(normalize_single(None), [])

    def test_kana_split(self):
        results = normalize_single("200-1-ア・イ・ウ")
        fulls = [r["full"] for r in results]
        self.assertEqual(fulls, ["200-1-ア", "200-1-イ", "200-1-ウ"])

    def test_kanji_with_oaza(self):
        """漢数字+大字のケース"""
        oaza_list = ["三本木"]
        results = normalize_single("三本木百二十五", oaza_list)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full"], "三本木125")


class TestRealWorldPatterns(unittest.TestCase):
    """実際のデータで見られるパターンのテスト"""

    def test_fullwidth_with_space_and_keyword(self):
        """「三本木　１２４ー１　借り」"""
        oaza = ["三本木"]
        results = normalize_single("三本木　１２４ー１　借り", oaza)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full"], "三本木124-1")

    def test_comma_separated_with_gai(self):
        """「大平沢201-1,2,3 外」"""
        oaza = ["大平沢"]
        results = normalize_single("大平沢201-1,2,3 外", oaza)
        fulls = [r["full"] for r in results]
        self.assertIn("大平沢201-1", fulls)
        self.assertIn("大平沢201-2", fulls)
        self.assertIn("大平沢201-3", fulls)

    def test_already_correct(self):
        """「大平沢201-1」（すでに正しい形式）"""
        oaza = ["大平沢"]
        results = normalize_single("大平沢201-1", oaza)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full"], "大平沢201-1")

    def test_repeated_full_chiban(self):
        """「三本木127-1、127-2、127-3」（すでに展開済み）"""
        oaza = ["三本木"]
        results = normalize_single("三本木127-1、127-2、127-3", oaza)
        fulls = [r["full"] for r in results]
        self.assertEqual(len(fulls), 3)
        self.assertIn("三本木127-1", fulls)
        self.assertIn("三本木127-2", fulls)
        self.assertIn("三本木127-3", fulls)


class TestKoazaAndPersonName(unittest.TestCase):
    """小字名・人名混在パターンのテスト"""

    def test_aza_with_person_name(self):
        """「内河野字吉富 1618-1-ｲ 日本太郎 借り」"""
        oaza = ["内河野"]
        results = normalize_single("内河野字吉富 1618-1-ｲ 日本太郎 借り", oaza)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["oaza"], "内河野")
        self.assertEqual(results[0]["chiban"], "1618-1-イ")
        self.assertEqual(results[0]["full"], "内河野1618-1-イ")

    def test_aza_removal(self):
        """小字名だけ除去して地番は残す"""
        oaza = ["内河野"]
        results = normalize_single("内河野字吉富 100-1", oaza)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full"], "内河野100-1")

    def test_person_name_after_chiban(self):
        """地番の後に人名がある場合、人名を除去"""
        oaza = ["三本木"]
        results = normalize_single("三本木123-1 山田花子", oaza)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["full"], "三本木123-1")


class TestParentParcelMatch(unittest.TestCase):
    """親地番マッチングのテスト"""

    def test_branch_to_parent(self):
        """1618-1-イ → マスターに1618-1があれば推測成功"""
        from land_parcel_normalizer.matcher import SISMatcher, MatchStatus
        master = {"内河野1618-1"}
        matcher = SISMatcher(master, ["内河野"])
        parcel = {"oaza": "内河野", "chiban": "1618-1-イ",
                  "full": "内河野1618-1-イ", "raw": "test"}
        result = matcher.match_single(parcel)
        self.assertEqual(result["status"], MatchStatus.INFERRED)
        self.assertEqual(result["matched_to"], "内河野1618-1")

    def test_exact_still_works(self):
        """枝番付きがマスターにあればそちらに完全一致"""
        from land_parcel_normalizer.matcher import SISMatcher, MatchStatus
        master = {"内河野1618-1-イ", "内河野1618-1"}
        matcher = SISMatcher(master, ["内河野"])
        parcel = {"oaza": "内河野", "chiban": "1618-1-イ",
                  "full": "内河野1618-1-イ", "raw": "test"}
        result = matcher.match_single(parcel)
        self.assertEqual(result["status"], MatchStatus.EXACT)
        self.assertEqual(result["matched_to"], "内河野1618-1-イ")


if __name__ == "__main__":
    unittest.main()
