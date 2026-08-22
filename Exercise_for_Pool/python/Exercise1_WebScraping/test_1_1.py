import importlib.util
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup


# 1-1.pyを読み込む
spec = importlib.util.spec_from_file_location(
    "scraping",
    "1-1.py"
)
scraping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraping)


class TestAddress(unittest.TestCase):

    def test_normal_address(self):
        result = scraping.split_street_address(
            "鍛冶町503"
        )

        self.assertEqual(
            result,
            ("鍛冶町", "503", "")
        )

    def test_address_with_building(self):
        result = scraping.split_street_address(
            "千歳町95-9花柳ビル1F"
        )

        self.assertEqual(
            result,
            ("千歳町", "95-9", "花柳ビル1F")
        )

    def test_numeric_town_name(self):
        result = scraping.split_street_address(
            "2条通8-569-1"
        )

        self.assertEqual(
            result,
            ("2条通", "8-569-1", "")
        )


class TestEmail(unittest.TestCase):

    def test_target_email(self):
        html = """
        <html>
            <a href="mailto:other@example.com">
                個人情報窓口
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
                運営会社へのお問い合わせ
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

    def test_no_email(self):
        html = """
        <html>
            <p>メールアドレスは掲載されていません。</p>
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

        session = Mock()

        with patch.object(
            scraping,
            "resolve_final_url",
            side_effect=lambda session, url: url
        ):
            result = scraping.extract_official_url(
                session,
                soup
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

        session = Mock()

        with patch.object(
            scraping,
            "resolve_final_url",
            side_effect=lambda session, url: url
        ):
            result = scraping.extract_official_url(
                session,
                soup
            )

        self.assertEqual(
            result,
            "https://official.example.com/"
        )

    def test_timeout_keeps_original_url(self):
        session = Mock()

        with patch.object(
            scraping,
            "request_page",
            side_effect=scraping.requests.Timeout()
        ):
            result = scraping.resolve_final_url(
                session,
                "https://shop.example.com/"
            )

        self.assertEqual(
            result,
            "https://shop.example.com/"
        )

    def test_captcha_keeps_original_url(self):
        session = Mock()

        response = Mock()
        response.url = (
            "https://example.com/captcha/"
        )

        with patch.object(
            scraping,
            "request_page",
            return_value=response
        ):
            result = scraping.resolve_final_url(
                session,
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

    def test_empty_url_is_false(self):
        self.assertFalse(
            scraping.check_ssl("")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)