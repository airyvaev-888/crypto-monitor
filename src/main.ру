import json
import os
from fetcher import build_snapshot
from analyzer import main as run_analyzer

SNAPSHOT_PATH = 'data/market_snapshot.json'


def main():
    os.makedirs('data', exist_ok=True)

    snapshot = build_snapshot()

    with open(SNAPSHOT_PATH, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"[INFO] Snapshot сохранён. Монет для анализа: {len(snapshot)}")

    run_analyzer()


if __name__ == '__main__':
    main()
