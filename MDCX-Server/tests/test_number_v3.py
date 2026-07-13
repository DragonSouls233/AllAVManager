"""
番号识别 v3.0 增强单元测试

测试覆盖：
1. 全角→半角归一化
2. CHS/CHT/CH 多字符中字后缀
3. 方括号中字标记扫描
4. 分集/版本后缀剥离
5. 综合场景（与 javdb 参考项目对比的 6 类边缘场景）

运行：
    cd O:\\MDCX\\MDCX-Server
    python -m pytest tests/test_number_v3.py -v
    # 或直接运行
    python tests/test_number_v3.py
"""
import os
import sys

# 让 tests/ 目录可以导入 app 包
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.scraper.number import (
    extract_number,
    parse_suffix,
    normalize_fullwidth,
    detect_chinese_bracket,
    strip_episode_suffix,
    normalize_number,
)


# ============================================
# 工具函数测试
# ============================================

def test_normalize_fullwidth():
    """全角→半角归一化"""
    assert normalize_fullwidth("ＡＢＣ－１２３") == "ABC-123"
    assert normalize_fullwidth("ａｂｃ_１２３") == "abc_123"
    assert normalize_fullwidth("ABC-123") == "ABC-123"  # 已是半角不变
    assert normalize_fullwidth("ＦＣ２－ＰＰＶ－１２３４５６") == "FC2-PPV-123456"
    assert normalize_fullwidth("") == ""
    assert normalize_fullwidth("中文测试") == "中文测试"  # 中文字符不受影响


def test_detect_chinese_bracket():
    """方括号中字标记检测"""
    assert detect_chinese_bracket("[中文字幕]ABC-123.mp4") is True
    assert detect_chinese_bracket("[中字]ABC-123.mp4") is True
    assert detect_chinese_bracket("[中文]ABC-123.mp4") is True
    assert detect_chinese_bracket("[CH]ABC-123.mp4") is True
    assert detect_chinese_bracket("[CHS]ABC-123.mp4") is True
    assert detect_chinese_bracket("[CHT]ABC-123.mp4") is True
    assert detect_chinese_bracket("[chs]ABC-123.mp4") is True  # 小写
    assert detect_chinese_bracket("[Chinese]ABC-123.mp4") is True
    assert detect_chinese_bracket("ABC-123.mp4") is False
    assert detect_chinese_bracket("[1080p]ABC-123.mp4") is False  # 分辨率方括号
    assert detect_chinese_bracket("[4K]ABC-123.mp4") is False


def test_strip_episode_suffix():
    """分集/版本后缀剥离"""
    # 分集字母
    assert strip_episode_suffix("ABC-123-A") == "ABC-123"
    assert strip_episode_suffix("ABC-123-B") == "ABC-123"
    # 分集数字
    assert strip_episode_suffix("ABC-123-1") == "ABC-123"
    assert strip_episode_suffix("ABC-123-12") == "ABC-123"
    # 版本号
    assert strip_episode_suffix("ABC-123-v2") == "ABC-123"
    assert strip_episode_suffix("ABC-123-r1") == "ABC-123"
    assert strip_episode_suffix("ABC-123-V2") == "ABC-123"  # 大写
    # 不应剥离 C/U 后缀（中字/无码标记）
    assert strip_episode_suffix("ABC-123-C") == "ABC-123-C"
    assert strip_episode_suffix("ABC-123-U") == "ABC-123-U"
    # 不应剥离 UC 后缀
    assert strip_episode_suffix("ABC-123-UC") == "ABC-123-UC"
    # 不应剥离 CHS/CHT 后缀
    assert strip_episode_suffix("ABC-123-CHS") == "ABC-123-CHS"
    # 基础番号不应被剥离
    assert strip_episode_suffix("ABC-123") == "ABC-123"
    assert strip_episode_suffix("FC2-123456") == "FC2-123456"


# ============================================
# parse_suffix 多字符后缀测试
# ============================================

def test_parse_suffix_chs_cht():
    """CHS/CHT/CH 后缀解析"""
    # CHS
    base, is_chinese, is_mosaic = parse_suffix("ABC-123-CHS")
    assert base == "ABC-123"
    assert is_chinese is True
    assert is_mosaic is None

    # CHT
    base, is_chinese, is_mosaic = parse_suffix("ABC-123-CHT")
    assert base == "ABC-123"
    assert is_chinese is True

    # CH
    base, is_chinese, is_mosaic = parse_suffix("ABC-123-CH")
    assert base == "ABC-123"
    assert is_chinese is True

    # 小写
    base, is_chinese, is_mosaic = parse_suffix("abc-123-chs")
    assert base == "ABC-123"
    assert is_chinese is True

    # 无分隔符
    base, is_chinese, is_mosaic = parse_suffix("ABC-123CHS")
    assert base == "ABC-123"
    assert is_chinese is True


def test_parse_suffix_uc_cu():
    """UC/CU 后缀（中字+无码）"""
    base, is_chinese, is_mosaic = parse_suffix("ABC-123-UC")
    assert base == "ABC-123"
    assert is_chinese is True
    assert is_mosaic is False

    base, is_chinese, is_mosaic = parse_suffix("ABC-123-CU")
    assert base == "ABC-123"
    assert is_chinese is True
    assert is_mosaic is False


def test_parse_suffix_single():
    """单字符后缀 C/U"""
    base, is_chinese, is_mosaic = parse_suffix("ABC-123-C")
    assert base == "ABC-123"
    assert is_chinese is True
    assert is_mosaic is None

    base, is_chinese, is_mosaic = parse_suffix("ABC-123-U")
    assert base == "ABC-123"
    assert is_chinese is None
    assert is_mosaic is False


def test_parse_suffix_none():
    """无后缀"""
    base, is_chinese, is_mosaic = parse_suffix("ABC-123")
    assert base == "ABC-123"
    assert is_chinese is None
    assert is_mosaic is None


# ============================================
# extract_number 综合测试（覆盖 javdb 对比文档 §10.4 的 6 类边缘场景）
# ============================================

def test_extract_fullwidth():
    """场景5：全角字符"""
    result = extract_number("ＡＢＣ－１２３.mp4")
    assert result.number == "ABC-123"
    assert result.number_type.value == "jav"


def test_extract_chs_suffix():
    """场景2：CHS/CHT 后缀"""
    result = extract_number("ABC-123-CHS.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True

    result = extract_number("ABC-123-CHT.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True

    result = extract_number("ABC-123-CH.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True


def test_extract_bracket_chinese():
    """场景1：方括号中字标记"""
    result = extract_number("[中文字幕]ABC-123.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True  # v3.0 应识别为中字

    result = extract_number("[CH]ABC-123.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True

    result = extract_number("[CHS]ABC-123.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True


def test_extract_bracket_chinese_with_normal_code():
    """方括号中字标记 + 普通番号（无 -C 后缀）"""
    # 没有方括号标记，也没有 -C 后缀 → 不是中字
    result = extract_number("ABC-123.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is None or result.is_chinese is False

    # 有方括号标记 → 是中字
    result = extract_number("[中字]ABC-123.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True


# ============================================
# 回归测试：原有功能不受影响
# ============================================

def test_extract_standard_jav():
    """标准 JAV 番号"""
    result = extract_number("ABC-123.mp4")
    assert result.number == "ABC-123"
    assert result.number_type.value == "jav"


def test_extract_fc2():
    """FC2 番号"""
    result = extract_number("FC2-PPV-1234567.mp4")
    assert "FC2" in result.number
    assert "1234567" in result.number
    assert result.number_type.value == "fc2"


def test_extract_heyyo():
    """HEYZO 无码番号"""
    result = extract_number("HEYZO-1234.mp4")
    assert "HEYZO" in result.number
    assert result.number_type.value == "uncensored"


def test_extract_with_c_suffix():
    """-C 后缀（中字）"""
    result = extract_number("ABC-123-C.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True


def test_extract_with_u_suffix():
    """-U 后缀（无码）"""
    result = extract_number("ABC-123-U.mp4")
    assert result.number == "ABC-123"
    assert result.is_mosaic is False


def test_extract_with_uc_suffix():
    """-UC 后缀（中字+无码）"""
    result = extract_number("ABC-123-UC.mp4")
    assert result.number == "ABC-123"
    assert result.is_chinese is True
    assert result.is_mosaic is False


# ============================================
# Comparator 集成测试（验证 strip_episode_suffix 在扫描流程中生效）
# ============================================

def test_scanner_strips_episode_suffix(tmp_path):
    """验证 LocalScanner.scan_directory 会剥离分集后缀"""
    from app.scraper.comparator import LocalScanner

    # 创建测试文件
    (tmp_path / "ABC-123-A.mp4").touch()
    (tmp_path / "ABC-123-B.mp4").touch()
    (tmp_path / "ABC-123-1.mp4").touch()
    (tmp_path / "ABC-123-v2.mp4").touch()
    (tmp_path / "DEF-456.mp4").touch()

    scanner = LocalScanner()
    codes = scanner.scan_directory(str(tmp_path))

    # 应该归并到 2 个基础番号
    code_set = {c.code for c in codes}
    assert "ABC-123" in code_set
    assert "DEF-456" in code_set
    # 不应出现分集后缀
    assert "ABC-123-A" not in code_set
    assert "ABC-123-B" not in code_set
    assert "ABC-123-1" not in code_set
    assert "ABC-123-V2" not in code_set


def test_scanner_fullwidth(tmp_path):
    """验证 LocalScanner.scan_directory 处理全角字符"""
    from app.scraper.comparator import LocalScanner

    (tmp_path / "ＡＢＣ－１２３.mp4").touch()

    scanner = LocalScanner()
    codes = scanner.scan_directory(str(tmp_path))

    code_set = {c.code for c in codes}
    assert "ABC-123" in code_set


def test_scanner_bracket_chinese(tmp_path):
    """验证 LocalScanner.scan_directory 识别方括号中字标记"""
    from app.scraper.comparator import LocalScanner

    (tmp_path / "[中文字幕]ABC-123.mp4").touch()
    (tmp_path / "DEF-456.mp4").touch()

    scanner = LocalScanner()
    codes = scanner.scan_directory(str(tmp_path))

    code_map = {c.code: c for c in codes}
    assert "ABC-123" in code_map
    assert code_map["ABC-123"].is_chinese is True  # v3.0 应识别为中字
    assert "DEF-456" in code_map
    assert code_map["DEF-456"].is_chinese is False  # 无标记，非中字


# ============================================
# 主入口
# ============================================

if __name__ == "__main__":
    # 简易测试运行器（不依赖 pytest）
    import inspect

    tests = [
        (name, func)
        for name, func in sorted(globals().items())
        if name.startswith("test_") and callable(func)
    ]
    passed = 0
    failed = 0
    for name, func in tests:
        try:
            # 检查是否需要 tmp_path 参数（pytest fixture）
            sig = inspect.signature(func)
            if "tmp_path" in sig.parameters:
                import tempfile
                from pathlib import Path
                with tempfile.TemporaryDirectory() as td:
                    func(Path(td))
            else:
                func()
            print(f"[PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"总计: {passed + failed}  通过: {passed}  失败: {failed}")
    print(f"{'=' * 50}")
    sys.exit(0 if failed == 0 else 1)
