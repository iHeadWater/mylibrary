"""Filter hydrology papers from a large corpus and categorize by topic."""
import argparse
import json
import re
from pathlib import Path

HYDRO_KEYWORDS = [
    (3, r"\bhydrolog(y|ical|ic)\b"),
    (3, r"\bstreamflow\b"),
    (3, r"\brunoff\b"),
    (3, r"\briver\s+discharge\b"),
    (3, r"\bflood\b"),
    (3, r"\bdrought\b"),
    (3, r"\bwatershed(s)?\b"),
    (3, r"\bcatchment(s)?\b"),
    (3, r"\bbasin(s)?\b"),
    (3, r"\breservoir(s)?\b"),
    (2, r"\bprecipitation\b"),
    (2, r"\brainfall\b"),
    (2, r"\bevapotranspiration\b"),
    (2, r"\bsoil\s+moisture\b"),
    (2, r"\bgroundwater\b"),
    (2, r"\binfiltration\b"),
    (2, r"\bwater\s+(resources|quality|level|temperature|budget|balance)\b"),
    (2, r"\bhydroclimate\b"),
    (2, r"\bsnowmelt\b"),
    (2, r"\bsnow\s+water\b"),
    (2, r"\bpermafrost\b"),
    (2, r"\bstream\s+(temperature|chemistry|flow)\b"),
    (2, r"\briverine\b"),
    (2, r"\bdam(s)?(\s+safety)?\b"),
    (2, r"\bhydrological\s+model(s|ing|ling)?\b"),
    (2, r"\bhydrologic\s+model(s|ing|ling)?\b"),
    (2, r"\brainfall[\-\s]runoff\b"),
    (2, r"\bstreamflow\s+(prediction|forecast|simulation|modeling|generation)\b"),
    (2, r"\bCAMELS\b"),
    (2, r"\bGR4J\b"),
    (2, r"\bSWAT\b"),
    (2, r"\bHBV\b"),
    (2, r"\bHYPE\b"),
    (2, r"\bWRF[\-\s]Hydro\b"),
    (2, r"\bPRMS\b"),
    (2, r"\bMESH\b"),
    (2, r"\bXinanjiang\b"),
    (2, r"\bTOPMODEL\b"),
    (2, r"\bSac[\-\s]?SMA\b"),
    (2, r"\bNash[\-\s]?Sutcliffe\b"),
    (2, r"\bKling[\-\s]?Gupta\b"),
    (2, r"\bhydraulic\s+model"),
    (2, r"\bshallow\s+water\s+equation"),
    (2, r"\bflood\s+(forecast|warning|prediction|model|simulation|inundation)\b"),
    (1, r"\bSMAP\b"),
    (1, r"\bGRACE\b"),
    (1, r"\bdata\s+assimilation.*\b(streamflow|discharge|hydrolog|flood)\b"),
    (1, r"\bphysics[\-\s](informed|guided|based|constrained).*\b(hydrolog|water|stream|flood)\b"),
    (1, r"\bdifferentiable.*\b(hydrolog|water|stream|flood)\b"),
    (1, r"\bLSTM.*\b(streamflow|discharge|hydrolog|flood|water|runoff|rainfall)\b"),
    (1, r"\bdeep\s+learning.*\b(streamflow|discharge|hydrolog|flood|water|runoff|rainfall|precipitation)\b"),
    (1, r"\bmachine\s+learning.*\b(streamflow|discharge|hydrolog|flood|water|runoff)\b"),
    (1, r"\bensemble.*\b(streamflow|discharge|flood|hydrolog)\b"),
    (1, r"\bhydrograph\b"),
    (1, r"\brating\s+curve\b"),
    (1, r"\bstage[\-\s]discharge\b"),
]

NOT_HYDRO = [
    r"\bprotein\b", r"\bgene\b", r"\bgenome\b", r"\bDNA\b", r"\bRNA\b",
    r"\bcancer\b", r"\bcardiac\b", r"\bechocardiogram\b",
    r"\bclinical\s+trial\b", r"\bquantum\b",
    r"\bGPT[\-\s]?(3|4|5)\b", r"\blarge\s+language\s+model\b",
    r"\bsorting\s+algorithm\b", r"\bDeepMind\b",
    r"\breinforcement\s+learning.*\b(game|chess|Go|Alpha)\b",
    r"\brobot\b", r"\bautonomous\s+vehicle\b", r"\bvideo\s+game\b",
]

TOPIC_RULES = [
    ("flood-inundation", [
        r"\bflood\b", r"\binundation\b", r"\bfloodplain\b",
        r"\bflood\s+(forecast|warning|risk|hazard)\b",
        r"\bhydraulic\s+model", r"\bshallow\s+water\b", r"\bHEC[\-\s]RAS\b",
    ]),
    ("streamflow-prediction", [
        r"\bstreamflow\b", r"\brunoff\b", r"\bdischarge\b", r"\briver\s+flow\b",
        r"\bstreamflow\s+(prediction|forecast|simulation|modeling)\b",
        r"\bGR4J\b", r"\bSWAT\b", r"\bHBV\b", r"\bHYPE\b", r"\bPRMS\b",
        r"\bTOPMODEL\b", r"\bXinanjiang\b",
        r"\bNash[\-\s]?Sutcliffe\b", r"\bKling[\-\s]?Gupta\b",
    ]),
    ("physics-informed-dl", [
        r"\bphysics[\-\s](informed|guided|based|constrained|encoded|aware)\b",
        r"\bdifferentiable\s+(model|programming|hydrolog)\b",
        r"\bPINN(s)?\b", r"\bphysics[\-\s]based\s+neural\b",
        r"\bprocess[\-\s]based.*\b(deep\s+learning|neural|machine\s+learning)\b",
    ]),
    ("data-assimilation", [
        r"\bdata\s+assimilation\b", r"\bensemble\s+Kalman\b", r"\bparticle\s+filter\b",
        r"\bEnKF\b", r"\bEnKS\b", r"\bLETKF\b", r"\b4D[\-\s]Var\b", r"\b3D[\-\s]Var\b",
    ]),
    ("precipitation-nowcasting", [
        r"\bprecipitation\b", r"\brainfall\b", r"\bnowcast(ing)?\b",
        r"\bQPE\b", r"\bQPF\b", r"\bIMERG\b", r"\bPERSIANN\b",
    ]),
    ("soil-moisture-groundwater", [
        r"\bsoil\s+moisture\b", r"\bgroundwater\b", r"\binfiltration\b",
        r"\bSMAP\b", r"\bSMOS\b", r"\bRichards?\s+equation\b",
        r"\bDarcy\b", r"\bvadose\b",
    ]),
    ("water-quality", [
        r"\bwater\s+quality\b", r"\bnitrogen\b", r"\bphosphorus\b",
        r"\bsediment\b", r"\bnutrient(s)?\s+(load|transport)\b",
        r"\bdissolved\s+oxygen\b", r"\bwater\s+temperature\b", r"\bstream\s+temperature\b",
    ]),
    ("remote-sensing-hydro", [
        r"\bremote\s+sensing.*\b(water|flood|hydrol|river|stream|lake)\b",
        r"\bGRACE\b", r"\baltimetr(y|ic).*\b(river|lake|water|flood)\b",
    ]),
    ("climate-hydro-extremes", [
        r"\bdrought\b", r"\bhydroclimate\b",
        r"\bclimate\s+change.*(water|hydrol|stream|flood)\b",
        r"\bextreme(s)?\s+(precipitation|rainfall|flood|flow|event)\b",
        r"\bCMIP[56]\b", r"\bGCM(s)?\b.*(hydrol|water|stream|flood)\b",
    ]),
    ("general-hydrology", [
        r"\bhydrolog(y|ical|ic)\b", r"\bwatershed(s)?\b", r"\bcatchment(s)?\b",
        r"\bbasin(s)?\b", r"\bwater\s+(resources|management|budget|balance)\b",
        r"\bevapotranspiration\b", r"\bCAMELS\b", r"\bGAGES[\-\s]?II\b",
        r"\breservoir(s)?\b",
    ]),
]


def score_paper(text: str) -> tuple[int, int]:
    text_lower = text.lower()
    score = 0
    for weight, pattern in HYDRO_KEYWORDS:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        if matches:
            score += weight * len(matches)
    penalty = 0
    for pattern in NOT_HYDRO:
        if re.search(pattern, text_lower, re.IGNORECASE):
            penalty += 5
    return score, penalty


def classify_topic(text: str) -> str:
    text_lower = text.lower()
    best_topic = "general-hydrology"
    best_score = 0
    for topic, patterns in TOPIC_RULES:
        score = sum(len(re.findall(p, text_lower, re.IGNORECASE)) for p in patterns)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic


def extract_snippet(text: str) -> str:
    lines = text.split("\n")
    collected = []
    for line in lines:
        if re.match(r'^#+\s*(introduction|I\.\s|1\.\s)', line, re.IGNORECASE):
            break
        collected.append(line)
        if len(collected) >= 300:
            break
    return "\n".join(collected)


def safe_copy(src: Path, dst_dir: Path, max_len: int = 240) -> Path:
    """Copy file with path-safe filename (Windows MAX_PATH guard)."""
    stem = src.stem[:180]  # truncate long titles
    dst = dst_dir / f"{stem}{src.suffix}"
    dst.write_bytes(src.read_bytes())
    return dst


def _existing_dir(value: str) -> Path:
    """argparse 类型：必须是已存在的目录，否则走标准报错 rc=2（而非深扫时裸抛）。"""
    path = Path(value)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"not an existing directory: {value}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filter_hydrology.py",
        description="Filter hydrology papers from a large corpus and categorize by topic.",
        epilog=(
            "example: uv run python scripts/filter_hydrology.py "
            '--source "G:/我的云端硬盘/Documents/Papers/Markdown" --target papers'
        ),
    )
    parser.add_argument(
        "--source",
        type=_existing_dir,
        required=True,
        help="Directory of source .md files to scan (read-only)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Directory to copy matched papers into, grouped by topic",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be processed; write nothing",
    )
    return parser


def main(source: Path, target: Path, *, dry_run: bool = False) -> None:
    print(f"Source: {source}")
    print(f"Target: {target}")
    if dry_run:
        print("Dry run: no files will be written")

    md_files = sorted(f for f in source.iterdir() if f.suffix == ".md" and f.is_file())
    print(f"Found {len(md_files)} markdown files")

    state_file = target / ".filter_state.json"
    processed = set()
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        processed = set(state.get("processed", []))

    results = {topic: [] for topic, _ in TOPIC_RULES}
    hydro_count = 0
    not_hydro_count = 0

    for i, fpath in enumerate(md_files):
        fname = fpath.name
        if fname in processed:
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            processed.add(fname)
            continue

        snippet = extract_snippet(content)
        score, penalty = score_paper(snippet)
        effective = score - penalty

        if effective >= 3:
            topic = classify_topic(snippet)
            results[topic].append(fname)
            if dry_run:
                print(f"  [dry-run] would copy {fname} -> {topic}/")
            else:
                dst_dir = target / topic
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst = dst_dir / fname
                if not dst.exists():
                    safe_copy(fpath, dst_dir)
            hydro_count += 1
        else:
            not_hydro_count += 1

        processed.add(fname)

        if (i + 1) % 500 == 0:
            pct = (i + 1) / len(md_files) * 100
            print(f"  {i+1}/{len(md_files)} ({pct:.0f}%) | hydro={hydro_count}, not={not_hydro_count}")

    if not dry_run:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({
            "processed": sorted(processed), "total": len(md_files),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"FILTER COMPLETE — {len(md_files)} files scanned")
    print(f"{'='*60}")
    print(f"Hydrology:  {hydro_count:>5} ({100*hydro_count/len(md_files):.1f}%)")
    print(f"Non-hydro:  {not_hydro_count:>5}")
    print(f"\nBy topic:")
    for topic, _ in TOPIC_RULES:
        n = len(results[topic])
        if n > 0:
            print(f"  {topic:<30s} {n:>5} papers")

    manifest = {
        "total_papers": len(md_files),
        "hydro_papers": hydro_count,
        "topics": {t: len(results[t]) for t in results if results[t]},
    }
    if dry_run:
        print(f"\nDry run complete — nothing written under {target}/")
        return
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nPapers copied to {target}/")


if __name__ == "__main__":
    args = build_parser().parse_args()
    main(args.source, args.target, dry_run=args.dry_run)
