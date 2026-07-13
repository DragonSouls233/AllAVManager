"""
补刮报告生成器

生成补刮统计报告：
- 缺失统计：哪些字段/图片缺失
- 补刮结果：成功/失败/跳过统计
- 详细日志：每项补刮的详情
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.patcher.detector import MissingInfo
from app.patcher.strategy import PatchResult, PatchStatus

logger = logging.getLogger(__name__)


@dataclass
class FieldStats:
    """字段统计"""
    field_name: str
    missing_count: int = 0
    patched_count: int = 0
    failed_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "missing_count": self.missing_count,
            "patched_count": self.patched_count,
            "failed_count": self.failed_count,
        }


@dataclass
class ImageStats:
    """图片统计"""
    image_type: str
    missing_count: int = 0
    patched_count: int = 0
    failed_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            "image_type": self.image_type,
            "missing_count": self.missing_count,
            "patched_count": self.patched_count,
            "failed_count": self.failed_count,
        }


@dataclass
class PatchReport:
    """补刮报告"""
    # 基本信息
    report_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    
    # 总体统计
    total_movies: int = 0
    total_missing_detected: int = 0
    total_patched: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    
    # 字段统计
    field_stats: dict[str, FieldStats] = field(default_factory=dict)
    
    # 图片统计
    image_stats: dict[str, ImageStats] = field(default_factory=dict)
    
    # 详细结果
    results: list[PatchResult] = field(default_factory=list)
    
    # 跳过的记录
    skipped_items: list[dict] = field(default_factory=list)
    
    def duration_seconds(self) -> float:
        """耗时（秒）"""
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
    
    def success_rate(self) -> float:
        """成功率"""
        if self.total_movies == 0:
            return 0.0
        return self.total_patched / self.total_movies * 100
    
    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds(),
            "total_movies": self.total_movies,
            "total_missing_detected": self.total_missing_detected,
            "total_patched": self.total_patched,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "success_rate": self.success_rate(),
            "field_stats": {k: v.to_dict() for k, v in self.field_stats.items()},
            "image_stats": {k: v.to_dict() for k, v in self.image_stats.items()},
            "results": [r.to_dict() for r in self.results],
            "skipped_items": self.skipped_items,
        }
    
    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def to_markdown(self) -> str:
        """转换为 Markdown"""
        lines = [
            "# 补刮报告",
            "",
            f"**报告ID**: {self.report_id}",
            f"**开始时间**: {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**结束时间**: {self.finished_at.strftime('%Y-%m-%d %H:%M:%S') if self.finished_at else '进行中'}",
            f"**耗时**: {self.duration_seconds():.2f} 秒",
            "",
            "## 总体统计",
            "",
            f"- 检测电影数: {self.total_movies}",
            f"- 发现缺失数: {self.total_missing_detected}",
            f"- 补刮成功数: {self.total_patched}",
            f"- 补刮失败数: {self.total_failed}",
            f"- 跳过数: {self.total_skipped}",
            f"- 成功率: {self.success_rate():.1f}%",
            "",
            "## 字段统计",
            "",
            "| 字段 | 缺失数 | 成功数 | 失败数 |",
            "|------|--------|--------|--------|",
        ]
        
        for field_name, stats in sorted(self.field_stats.items()):
            lines.append(
                f"| {field_name} | {stats.missing_count} | "
                f"{stats.patched_count} | {stats.failed_count} |"
            )
        
        lines.extend([
            "",
            "## 图片统计",
            "",
            "| 图片类型 | 缺失数 | 成功数 | 失败数 |",
            "|----------|--------|--------|--------|",
        ])
        
        for image_type, stats in sorted(self.image_stats.items()):
            lines.append(
                f"| {image_type} | {stats.missing_count} | "
                f"{stats.patched_count} | {stats.failed_count} |"
            )
        
        if self.skipped_items:
            lines.extend([
                "",
                "## 跳过记录",
                "",
            ])
            for item in self.skipped_items[:10]:  # 只显示前10条
                lines.append(f"- {item.get('code', 'Unknown')}: {item.get('reason', 'Unknown')}")
        
        lines.append("")
        return "\n".join(lines)


class PatchReporter:
    """
    补刮报告生成器
    
    收集补刮过程中的数据，生成统计报告
    """
    
    def __init__(self, report_id: Optional[str] = None):
        """
        初始化
        
        Args:
            report_id: 报告ID（默认自动生成）
        """
        self.report_id = report_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.report = PatchReport(
            report_id=self.report_id,
            started_at=datetime.now(),
        )
    
    def add_missing_info(self, missing_info: MissingInfo):
        """添加缺失检测结果"""
        self.report.total_missing_detected += 1
        
        # 统计字段缺失
        for field in missing_info.missing_fields:
            field_name = field.field_type.value
            if field_name not in self.report.field_stats:
                self.report.field_stats[field_name] = FieldStats(field_name=field_name)
            self.report.field_stats[field_name].missing_count += 1
        
        # 统计图片缺失
        for image in missing_info.missing_images:
            image_type = image.image_type.value
            if image_type not in self.report.image_stats:
                self.report.image_stats[image_type] = ImageStats(image_type=image_type)
            self.report.image_stats[image_type].missing_count += 1
    
    def add_result(self, result: PatchResult):
        """添加补刮结果"""
        self.report.results.append(result)
        self.report.total_movies += 1
        
        if result.status == PatchStatus.SUCCESS:
            self.report.total_patched += 1
        elif result.status == PatchStatus.PARTIAL:
            self.report.total_patched += 1
        elif result.status == PatchStatus.FAILED:
            self.report.total_failed += 1
        elif result.status == PatchStatus.SKIPPED:
            self.report.total_skipped += 1
        
        # 更新字段统计
        for field_name in result.patched_fields:
            if field_name in self.report.field_stats:
                self.report.field_stats[field_name].patched_count += 1
        
        for field_name in result.failed_fields:
            if field_name in self.report.field_stats:
                self.report.field_stats[field_name].failed_count += 1
        
        # 更新图片统计
        for image_type in result.patched_images:
            if image_type in self.report.image_stats:
                self.report.image_stats[image_type].patched_count += 1
        
        for image_type in result.failed_images:
            if image_type in self.report.image_stats:
                self.report.image_stats[image_type].failed_count += 1
    
    def add_skipped(self, movie_code: str, reason: str, message: str):
        """添加跳过记录"""
        self.report.skipped_items.append({
            "code": movie_code,
            "reason": reason,
            "message": message,
        })
        self.report.total_skipped += 1
    
    def finalize(self) -> PatchReport:
        """完成报告"""
        self.report.finished_at = datetime.now()
        return self.report
    
    def save_report(
        self,
        output_dir: str,
        format: str = "json",  # json/markdown/both
    ) -> list[str]:
        """
        保存报告到文件
        
        Args:
            output_dir: 输出目录
            format: 输出格式
            
        Returns:
            保存的文件路径列表
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        
        if format in ("json", "both"):
            json_file = output_path / f"patch_report_{self.report_id}.json"
            json_file.write_text(self.report.to_json(), encoding="utf-8")
            saved_files.append(str(json_file))
            logger.info(f"Saved JSON report: {json_file}")
        
        if format in ("markdown", "both"):
            md_file = output_path / f"patch_report_{self.report_id}.md"
            md_file.write_text(self.report.to_markdown(), encoding="utf-8")
            saved_files.append(str(md_file))
            logger.info(f"Saved Markdown report: {md_file}")
        
        return saved_files
    
    def get_summary(self) -> dict:
        """获取摘要"""
        return {
            "report_id": self.report_id,
            "total_movies": self.report.total_movies,
            "total_missing": self.report.total_missing_detected,
            "total_patched": self.report.total_patched,
            "total_failed": self.report.total_failed,
            "total_skipped": self.report.total_skipped,
            "success_rate": f"{self.report.success_rate():.1f}%",
            "duration": f"{self.report.duration_seconds():.2f}s",
        }


def create_report(
    missing_infos: list[MissingInfo],
    results: list[PatchResult],
    skipped: Optional[list[dict]] = None,
) -> PatchReport:
    """
    创建补刮报告的便捷函数
    
    Args:
        missing_infos: 缺失信息列表
        results: 补刮结果列表
        skipped: 跳过记录列表
        
    Returns:
        PatchReport 补刮报告
    """
    reporter = PatchReporter()
    
    for info in missing_infos:
        reporter.add_missing_info(info)
    
    for result in results:
        reporter.add_result(result)
    
    if skipped:
        for item in skipped:
            reporter.add_skipped(
                item.get("code", ""),
                item.get("reason", ""),
                item.get("message", ""),
            )
    
    return reporter.finalize()
