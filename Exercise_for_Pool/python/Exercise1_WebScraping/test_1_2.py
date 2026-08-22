import importlib.util
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup


# 1-2.pyを読み込む
spec = importlib.util.spec_from_file_location(
    "scraping",
    "1-2.py"
)
scraping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraping)


class TestAddress(unittest.TestCase):

    def test_normal_address(self):
        self.assertEqual(
            scraping.split_street_address("鍛冶町503"),
            ("鍛冶町", "503", "")
        )

    def test_address_with_building(self):
        self.assertEqual(
            scraping.split_street_address(
                "千歳町95-9花柳ビル1F"
            ),
            ("千歳町", "95-9", "花柳ビル1F")
        )

    def test_numeric_town_name(self):
        self.assertEqual(
            scraping.split_street_address(
                "2条通8-569-1"
            ),
            ("2条通", "8-569-1", "")
        )


class TestEmail(unittest.TestCase):

    def test_target_email(self):
        html = """
        <html>
            <a href="mailto:other@example.com">
                運営会社への問い合わせ
            </a>

            <a href="mailto:shop@example.com">
                お店に直接メールする
            </a>
        </html>
        """

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        self.assertEqual(
            scraping.extract_email(soup),
            "shop@example.com"
        )

    def test_ignore_other_email(self):
        html = """
        <html>
            <a href="mailto:other@example.com">
                個人情報窓口
            </a>
        </html>
        """

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        self.assertEqual(
            scraping.extract_email(soup),
            ""
        )

    def test_no_target_email(self):
        soup = BeautifulSoup(
            "<html><p>メールなし</p></html>",
            "html.parser"
        )

        self.assertEqual(
            scraping.extract_email(soup),
            ""
        )


class TestURL(unittest.TestCase):

    def test_homepage_has_priority(self):
        html = """
        <html>
            <a href="https://official.example.com/">
                オフィシャル ページ
            </a>

            <a href="https://homepage.example.com/">
                お店のホームページ
            </a>
        </html>
        """

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        driver = Mock()

        with patch.object(
            scraping,
            "resolve_final_url",
            side_effect=lambda driver, url: url
        ):
            result = scraping.extract_official_url(
                driver,
                soup,
                "https://r.gnavi.co.jp/test/"
            )

        self.assertEqual(
            result,
            "https://homepage.example.com/"
        )

    def test_official_page_fallback(self):
        html = """
        <html>
            <a href="https://official.example.com/">
                オフィシャル ページ
            </a>
        </html>
        """

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        driver = Mock()

        with patch.object(
            scraping,
            "resolve_final_url",
            side_effect=lambda driver, url: url
        ):
            result = scraping.extract_official_url(
                driver,
                soup,
                "https://r.gnavi.co.jp/test/"
            )

        self.assertEqual(
            result,
            "https://official.example.com/"
        )

    def test_captcha_keeps_original_url(self):
        driver = Mock()

        driver.current_window_handle = "main"
        driver.window_handles = ["main", "tab"]

        driver.current_url = (
            "https://example.com/captcha/"
        )

        result = scraping.resolve_final_url(
            driver,
            "https://shop.example.com/"
        )

        self.assertEqual(
            result,
            "https://shop.example.com/"
        )


class TestSSL(unittest.TestCase):

    def test_http_is_false(self):
        self.assertFalse(
            scraping.check_ssl(
                "http://example.com/"
            )
        )

    def test_empty_is_false(self):
        self.assertFalse(
            scraping.check_ssl("")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)