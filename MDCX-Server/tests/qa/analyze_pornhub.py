"""
验证 PORNHUB 扫描器的目录解析逻辑
"""
import sys
from pathlib import Path

# 模拟 PornhubScanner 的逻辑
sys.path.insert(0, "G:/MDCX/MDCX-Server")
from app.tasks.pornhub_scanner import extract_actor_and_nationality, extract_pornhub_code, _NATIONALITY_PATTERNS

print("=== 测试 extract_actor_and_nationality ===")
test_names = [
    "俄罗斯",
    "美国", 
    "素人",
    "Anna Cherry7",
    "[Channel] Anna Cherry7",
    "Anna Cherry7 [US]",
    "爱沙尼亚",
    "[Channel] Diana Rider",
    "Diana Rider",
    "日本",
    "中国",
    "XXX",
    "V",
    "v",
]

for name in test_names:
    actor, nat = extract_actor_and_nationality(name)
    is_nat = name in _NATIONALITY_PATTERNS
    print(f"  folder='{name}' -> actor='{actor}', nationality='{nat}', is_nationality_in_dict={is_nat}")

print("\n=== 分析问题 ===")
print("""
PORNHUB media_dirs = ['M:\\', 'N:\\', 'O:\\']
如果 M: 盘根目录下是：
  M:\\
    美国\\        ← 第一级目录：国籍
      Anna_Cherry7\\  ← 第二级目录：演员
        video1.mp4
    俄罗斯\\
      XXX\\
        video.mp4

当文件在 M:\\俄罗斯\\XXX\\video.mp4:
  _get_actor_from_path 会:
    rel_path = 俄罗斯\\XXX\\video.mp4
    parent_dir = 俄罗斯\\XXX
    folder_name = XXX  → extract_actor_and_nationality("XXX") → ("XXX", None)
    这应该能正确提取 actor="XXX"
    
但如果文件直接在 M:\\俄罗斯\\video.mp4:
    rel_path = 俄罗斯\\video.mp4  
    parent_dir = 俄罗斯
    folder_name = 俄罗斯  → extract_actor_and_nationality("俄罗斯") → ("俄罗斯", None)
    → 这就是BUG！"俄罗斯"被当成了演员名

另外看 _scan_directory 方法的 walk:
  for root, dirs, files in os.walk(media_dir):
    actor_name, nationality = self._get_actor_from_path(root, media_dir)
    
  这里 root 是绝对路径如 M:\\俄罗斯, _get_actor_from_path 用 root 作为 file_path 参数
  但实际上 file_path 参数应该是文件路径，这里传入了目录路径！
  所以 _get_actor_from_path 中的 parent_dir = rel_path.parent 会得到父目录
  
  M:\\俄罗斯 → rel_path = 俄罗斯
  parent_dir = .  → 返回 None, None
  
  哦等等，那应该返回 None 而不是"俄罗斯"... 让我再仔细看
""")

# 模拟 _scan_directory 中的 walk
import os

print("\n=== 模拟 os.walk 行为 ===")
media_dir = Path("M:\\")
test_structure = [
    ("M:\\", ["美国", "俄罗斯", "素人"], []),
    ("M:\\美国", ["Anna Cherry7"], []),
    ("M:\\美国\\Anna Cherry7", [], ["video1.mp4", "video2.mp4"]),
    ("M:\\俄罗斯", ["XXX"], []),
    ("M:\\俄罗斯\\XXX", [], ["video.mp4"]),
    ("M:\\素人", [], ["direct_video.mp4"]),
]

# 模拟 _get_actor_from_path 在 _scan_directory 中的使用
def _get_actor_from_path(file_path: Path, media_dir: Path) -> tuple:
    try:
        rel_path = Path(file_path).relative_to(media_dir)
    except ValueError:
        return None, None
    
    parent_dir = rel_path.parent
    if parent_dir == Path("."):
        return None, None
    
    folder_name = parent_dir.name if parent_dir != Path(".") else None
    if not folder_name:
        return None, None
    
    from app.tasks.pornhub_scanner import extract_actor_and_nationality, _NATIONALITY_PATTERNS
    actor_name, nationality = extract_actor_and_nationality(folder_name)
    
    if not nationality and parent_dir.parent != Path("."):
        grandparent_name = parent_dir.parent.name
        if grandparent_name in _NATIONALITY_PATTERNS:
            nationality = _NATIONALITY_PATTERNS[grandparent_name]
    
    return actor_name, nationality

for root, dirs, files in test_structure:
    print(f"\n  root={root}")
    for f in files:
        fp = Path(root) / f
        actor, nat = _get_actor_from_path(fp, media_dir)
        print(f"    文件 {f}: actor='{actor}', nationality='{nat}'")
    # 这里注意！_scan_directory 把 root 当 file_path 传给 _get_actor_from_path
    # 但实际上应该分析每个文件！
    for d in dirs:
        dp = Path(root) / d
        actor, nat = _get_actor_from_path(dp, media_dir)
        print(f"    目录 {d} (作为文件传入): actor='{actor}', nationality='{nat}'")

print("\n=== 结论 ===")
print("""
API数据显示PORNHUB演员有: '素人'(16部), '俄罗斯'(13部), '美国'(13部)...
这意味着有视频文件直接位于国籍目录下(没有演员子目录)，导致国籍名被当成演员名。

错误场景:
  M:\\素人\\direct_video.mp4
  → rel_path = 素人\\direct_video.mp4
  → parent_dir = 素人
  → folder_name = 素人
  → extract_actor_and_nationality("素人") → ("素人", None)
  → actor = "素人" ← 错误！应为 None 或跳过

正确的做法: 当目录层级只有一级（国籍/演员没有二级目录）时，
不应将国籍/顶层目录名作为演员名。
""")
