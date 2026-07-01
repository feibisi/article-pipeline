#!/usr/bin/env python3
"""品类域验证工具 - 检查所有品类目录符合 _schema.yaml 契约"""

import os
import sys
import yaml
from pathlib import Path

GENRES_DIR = Path(__file__).parent.parent / "article_pipeline" / "genres"

def validate_manifest(domain_dir: Path) -> list[str]:
    """检查 manifest.yaml 存在且字段完整"""
    errors = []
    manifest_path = domain_dir / "manifest.yaml"
    if not manifest_path.exists():
        return [f"{domain_dir.name}/manifest.yaml 不存在"]
    with open(manifest_path) as f:
        data = yaml.safe_load(f)
    required = ["domain", "name", "description", "version", "status",
                "trigger_keywords", "trust_tier", "injection_level"]
    for field in required:
        if field not in data:
            errors.append(f"{domain_dir.name}/manifest.yaml 缺少字段: {field}")
    return errors

def validate_style_preset(domain_dir: Path) -> list[str]:
    """检查 style_preset.yaml 存在且 vector 5 维度值在 [-1, 1]"""
    errors = []
    preset_path = domain_dir / "style_preset.yaml"
    if not preset_path.exists():
        return [f"{domain_dir.name}/style_preset.yaml 不存在"]
    with open(preset_path) as f:
        data = yaml.safe_load(f)
    if "vector" not in data:
        return [f"{domain_dir.name}/style_preset.yaml 缺少 vector"]
    vector = data["vector"]
    dimensions = ["density", "warmth", "energy", "register", "edge"]
    for dim in dimensions:
        if dim not in vector:
            errors.append(f"{domain_dir.name}/style_preset.yaml vector 缺少维度: {dim}")
        elif not -1.0 <= vector[dim] <= 1.0:
            errors.append(f"{domain_dir.name}/style_preset.yaml {dim}={vector[dim]} 超出 [-1, 1] 范围")
    return errors

def validate_genre_rules(domain_dir: Path) -> list[str]:
    """检查 genre_rules.yaml 存在且非空"""
    rules_path = domain_dir / "genre_rules.yaml"
    if not rules_path.exists():
        return [f"{domain_dir.name}/genre_rules.yaml 不存在"]
    with open(rules_path) as f:
        content = f.read().strip()
    if not content or len(content) < 10:
        return [f"{domain_dir.name}/genre_rules.yaml 内容为空或过短"]
    return []

def validate_prosody_samples(domain_dir: Path) -> list[str]:
    """检查 prosody_samples/ 目录至少有 1 个 .txt 文件"""
    samples_dir = domain_dir / "prosody_samples"
    if not samples_dir.exists():
        return [f"{domain_dir.name}/prosody_samples/ 目录不存在"]
    txt_files = list(samples_dir.glob("*.txt"))
    if len(txt_files) == 0:
        return [f"{domain_dir.name}/prosody_samples/ 没有 .txt 文件"]
    return []

def validate_constraints(domain_dir: Path) -> list[str]:
    """检查 style_preset.yaml 的 constraints 有 require + avoid（allow 可选）"""
    preset_path = domain_dir / "style_preset.yaml"
    if not preset_path.exists():
        return []
    with open(preset_path) as f:
        data = yaml.safe_load(f)
    if "constraints" not in data:
        return [f"{domain_dir.name}/style_preset.yaml 缺少 constraints"]
    constraints = data["constraints"]
    errors = []
    if "require" not in constraints or not constraints["require"]:
        errors.append(f"{domain_dir.name}/style_preset.yaml constraints.require 为空")
    if "avoid" not in constraints or not constraints["avoid"]:
        errors.append(f"{domain_dir.name}/style_preset.yaml constraints.avoid 为空")
    return errors

def main():
    if not GENRES_DIR.exists():
        print(f"错误: genres 目录不存在: {GENRES_DIR}")
        sys.exit(1)

    all_errors = []
    domain_dirs = [d for d in GENRES_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")]

    for domain_dir in domain_dirs:
        errors = []
        errors.extend(validate_manifest(domain_dir))
        errors.extend(validate_style_preset(domain_dir))
        errors.extend(validate_genre_rules(domain_dir))
        errors.extend(validate_prosody_samples(domain_dir))
        errors.extend(validate_constraints(domain_dir))

        if errors:
            all_errors.extend(errors)
            print(f"❌ {domain_dir.name}: {len(errors)} 个错误")
        else:
            print(f"✅ {domain_dir.name}")

    if all_errors:
        print(f"\n共 {len(all_errors)} 个错误:")
        for err in all_errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print(f"\n全部通过: {len(domain_dirs)} 个品类")
        sys.exit(0)

if __name__ == "__main__":
    main()
