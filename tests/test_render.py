"""渲染测试：页面产出 / hreflang / 双语 / 发布守门（§10.1 验收项 #6 / #10）。"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tidewatch.pipeline.sectors import run_sectors
from tidewatch.render.builder import SiteBuilder
from tidewatch.render.publish import count_pages, publish
from tidewatch.store.db import Store
from tests.helpers import kline_fake

TARGET = "2026-09-30"
CODES = ["881101", "881121", "881273"]


def _store_with_data(tmp: Path) -> Store:
    store = Store(tmp / "t.db")
    store.init_schema()
    run_sectors(store, kline_fake(), sector_codes=CODES,
                category="industry", target_date=TARGET)
    return store


class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.store = _store_with_data(self.tmpdir)
        self.out = self.tmpdir / "dist.new"

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_page_count(self):
        res = SiteBuilder(self.store, self.out).build(TARGET)
        # 每语言：首页 + 板块列表 + 游资列表 + 资金雷达 + 个股列表 + 3 个板块详情 = 8；× 2 = 16
        self.assertEqual(res["pages"], 16)
        self.assertEqual(count_pages(self.out), 16)
        for p in ("index.html", "sectors/index.html", "sectors/881121/index.html",
                  "people/index.html", "radar/index.html", "stocks/index.html"):
            self.assertTrue((self.out / p).exists(), p)
            self.assertTrue((self.out / "en" / p).exists(), f"en/{p}")

    def test_hreflang_and_canonical(self):
        SiteBuilder(self.store, self.out, base_url="https://example.cn").build(TARGET)
        h = (self.out / "en" / "sectors" / "881121" / "index.html").read_text(encoding="utf-8")
        # canonical 各自指向自己
        self.assertIn('rel="canonical" href="https://example.cn/en/sectors/881121/"', h)
        # 双向 hreflang（SEO 保留）
        self.assertIn('hreflang="zh-CN" href="https://example.cn/sectors/881121/"', h)
        self.assertIn('hreflang="en" href="https://example.cn/en/sectors/881121/"', h)

    def test_english_names(self):
        SiteBuilder(self.store, self.out).build(TARGET)
        zh = (self.out / "sectors" / "index.html").read_text(encoding="utf-8")
        en = (self.out / "en" / "sectors" / "index.html").read_text(encoding="utf-8")
        self.assertIn("半导体", zh)
        self.assertIn("Semiconductors", en)
        # 英文页不应出现中文板块名
        self.assertNotIn("半导体", en)

    def test_lang_switch_hidden_by_default(self):
        """语言切换按用户要求暂时屏蔽（hreflang 仍保留）。"""
        SiteBuilder(self.store, self.out).build(TARGET)
        zh = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="lang-switch"', zh)
        # 但 hreflang 仍在（不影响 SEO）
        self.assertIn('hreflang="en"', zh)

    def test_lang_switch_can_be_enabled(self):
        SiteBuilder(self.store, self.out, show_lang_switch=True).build(TARGET)
        zh = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="lang-switch" href="/en/"', zh)

    def test_nav_highlight_not_always_sectors(self):
        """导航高亮跟随当前页（之前硬编码高亮板块图谱）。"""
        SiteBuilder(self.store, self.out).build(TARGET)
        for path, expect in (("sectors/index.html", "sectors"),
                             ("people/index.html", "people"),
                             ("radar/index.html", "radar"),
                             ("stocks/index.html", "stocks")):
            html = (self.out / path).read_text(encoding="utf-8")
            self.assertIn(f'href="/{expect}/" class="active"', html, path)
            # 只有一个 active
            self.assertEqual(html.count('class="active"'), 1, path)

    def test_sort_script_included(self):
        SiteBuilder(self.store, self.out).build(TARGET)
        html = (self.out / "sectors" / "index.html").read_text(encoding="utf-8")
        self.assertIn('/assets/sort.js', html)
        self.assertTrue((self.out / "assets" / "sort.js").exists())

    def test_sector_scope_label(self):
        """界面标注板块覆盖范围（全量 vs Top N）。"""
        SiteBuilder(self.store, self.out).build(TARGET)
        html = (self.out / "sectors" / "index.html").read_text(encoding="utf-8")
        self.assertIn("覆盖范围", html)
        self.assertIn("行业板块全量", html)

    def test_no_hardcoded_locale_in_template(self):
        """模板里不应出现硬编码中文（i18n 要求）。"""
        tpl_dir = Path("src/tidewatch/render/templates")
        if not tpl_dir.exists():
            self.skipTest("templates dir not found from cwd")
        for f in tpl_dir.glob("*.html"):
            txt = f.read_text(encoding="utf-8")
            cjk = re.findall(r"[\u4e00-\u9fff]+", txt)
            self.assertEqual(cjk, [], f"hardcoded CJK in {f.name}: {cjk[:5]}")


class TestPublishGuard(unittest.TestCase):
    def test_refuse_when_too_few_pages(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "new"
            d.mkdir()
            (d / "a.html").write_text("x", encoding="utf-8")
            ok, msg = publish(d, Path(t) / "dist", min_pages=6)
            self.assertFalse(ok)
            self.assertIn("refused", msg)
            # 原目录未被创建/替换
            self.assertFalse((Path(t) / "dist").exists())

    def test_publish_atomic(self):
        with tempfile.TemporaryDirectory() as t:
            new, final = Path(t) / "new", Path(t) / "dist"
            new.mkdir()
            for i in range(8):
                (new / f"{i}.html").write_text("x", encoding="utf-8")
            final.mkdir()
            (final / "old.html").write_text("old", encoding="utf-8")
            ok, msg = publish(new, final, min_pages=6)
            self.assertTrue(ok)
            self.assertEqual(count_pages(final), 8)
            self.assertFalse((final / "old.html").exists())


if __name__ == "__main__":
    unittest.main()
