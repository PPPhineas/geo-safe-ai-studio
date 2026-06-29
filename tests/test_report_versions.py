from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.api.schemas import ReportAnnotationInput, RiskReportReviseRequest
from app.pipeline import orchestrator


class FakeRevisionClient:
    def __init__(self, raw: str | Exception) -> None:
        self.raw = raw

    def judge(self, system: str, user: str, *, retries: int = 2) -> str:
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


class ReportVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_output_dir = orchestrator.OUTPUT_DIR
        orchestrator.OUTPUT_DIR = Path(self.tmp.name)

    def tearDown(self) -> None:
        orchestrator.OUTPUT_DIR = self.old_output_dir
        self.tmp.cleanup()

    def _write_legacy_report(self, report_id: str = "rpt_demo") -> Path:
        target = orchestrator.OUTPUT_DIR / report_id
        target.mkdir(parents=True)
        (target / "report.md").write_text(
            "# 风险报告\n\n![map](/static/figures/rpt_demo/map_figure.png)\n\n原始段落",
            encoding="utf-8",
        )
        (target / "map_figure.png").write_bytes(b"png")
        (target / "monitor_points.csv").write_text("code\nPT001\n", encoding="utf-8")
        (target / "judgement.json").write_text("{}", encoding="utf-8")
        return target

    def test_legacy_report_is_exposed_as_v1(self) -> None:
        self._write_legacy_report()

        detail = orchestrator.get_risk_report("rpt_demo")

        self.assertEqual(detail.current_version, 1)
        self.assertEqual(detail.current.version_id, "rpt_demo_v1")
        self.assertIn("原始段落", detail.current.report_markdown)
        self.assertEqual(
            detail.current.figures["map_figure"],
            "/static/figures/rpt_demo/map_figure.png",
        )
        self.assertEqual(
            detail.current.attachments["monitor_points.csv"],
            "/static/figures/rpt_demo/monitor_points.csv",
        )

    def test_revise_creates_v2_and_bundle_can_choose_versions(self) -> None:
        target = self._write_legacy_report()
        req = RiskReportReviseRequest(
            base_version_id="rpt_demo_v1",
            annotations=[
                ReportAnnotationInput(
                    block_id="block_1",
                    block_text="原始段落",
                    comment="补充依据",
                )
            ],
        )
        raw = json.dumps(
            {
                "report_markdown": "# 风险报告\n\n修订段落",
                "change_summary": ["补充依据"],
            },
            ensure_ascii=False,
        )

        resp = orchestrator.revise_risk_report("rpt_demo", req, FakeRevisionClient(raw))

        self.assertEqual(resp.version_id, "rpt_demo_v2")
        self.assertEqual(resp.version, 2)
        self.assertEqual(resp.change_summary, ["补充依据"])
        self.assertIn("原始段落", (target / "report.md").read_text(encoding="utf-8"))
        self.assertIn(
            "修订段落",
            (target / "versions" / "rpt_demo_v2" / "report.md").read_text(encoding="utf-8"),
        )

        with zipfile.ZipFile(io.BytesIO(orchestrator.build_bundle("rpt_demo", "rpt_demo_v1"))) as zf:
            self.assertIn("原始段落", zf.read("report.md").decode("utf-8"))
        with zipfile.ZipFile(io.BytesIO(orchestrator.build_bundle("rpt_demo"))) as zf:
            self.assertIn("修订段落", zf.read("report.md").decode("utf-8"))

    def test_failed_revision_does_not_create_new_version(self) -> None:
        target = self._write_legacy_report()
        req = RiskReportReviseRequest(
            base_version_id="rpt_demo_v1",
            annotations=[
                ReportAnnotationInput(
                    block_id="block_1",
                    block_text="原始段落",
                    comment="补充依据",
                )
            ],
        )

        with self.assertRaises(RuntimeError):
            orchestrator.revise_risk_report("rpt_demo", req, FakeRevisionClient(RuntimeError("boom")))

        index = json.loads((target / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual(index["current_version"], 1)
        self.assertFalse((target / "versions").exists())


if __name__ == "__main__":
    unittest.main()
