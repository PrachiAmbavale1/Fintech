from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent import Orchestrator
from memory import PreferenceMemory
from scheduler import run_daily_scheduler


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fintech daily news brief")
    p.add_argument("--run-now", action="store_true", help="Run one brief now")
    p.add_argument(
        "--schedule",
        action="store_true",
        help="Run daily at email_hour from config.yaml",
    )
    p.add_argument("--demo", action="store_true", help="Use sample articles instead of live search")
    p.add_argument("--feedback", choices=["more", "less", "neutral"], help="Update topic/company preference")
    p.add_argument("--topic", type=str, help="Topic for --feedback")
    p.add_argument("--company", type=str, help="Company for --feedback")
    p.add_argument("--config", type=str, default="config.yaml")
    p.add_argument(
        "--align-send",
        action="store_true",
        help="After building the brief, wait until config email_hour/minute (Asia/Kolkata) before sending",
    )
    p.add_argument(
        "--sync-calendar",
        action="store_true",
        help="Create or update the Google Calendar reminder",
    )
    return p.parse_args()


def print_brief(brief) -> None:
    print("\nBrief ready")
    print(f"Subject : {brief.subject}")
    print(f"Stories : {len(brief.stories)}")
    print(f"Raw     : {brief.raw_count} | Relevant: {brief.relevant_count} | Rounds: {brief.search_rounds}")
    print(f"Timezone: {brief.timezone}")
    print("Output  : sample_email.html and data/runs/")
    print("\nStories:")
    for i, s in enumerate(brief.stories, 1):
        print(f"  {i}. [{s.publication}] {s.title}")
        print(f"     score={s.final_score:.2f}" if s.final_score is not None else "")


def run_once(args, memory: PreferenceMemory):
    orch = Orchestrator(config_path=args.config, memory=memory, use_sample=args.demo)
    brief = orch.run(align_send=bool(getattr(args, "align_send", False)))
    print_brief(brief)
    return brief


def main() -> int:
    load_dotenv()
    setup_logging()
    args = parse_args()

    Path("data/runs").mkdir(parents=True, exist_ok=True)
    memory = PreferenceMemory("data/memory.db")

    if args.feedback:
        if not args.topic and not args.company:
            print("Provide --topic and/or --company with --feedback")
            return 2
        memory.apply_feedback(args.feedback, topic=args.topic, company=args.company)
        prefs = memory.load_preferences()
        print("Updated preferences:")
        for k, v in sorted(prefs.items(), key=lambda x: x[1], reverse=True)[:8]:
            print(f"  {k}: {v:.2f}")
        if not args.run_now and not args.schedule:
            return 0

    if args.sync_calendar:
        from calendar_tool import ensure_daily_brief_event

        ensure_daily_brief_event(args.config)

    if args.schedule:
        def job() -> None:
            run_once(args, memory)

        print(f"Scheduler started ({args.config}: email_hour / timezone)")
        print("Leave this process running. Ctrl+C to stop.\n")
        run_daily_scheduler(
            job,
            config_path=args.config,
            run_immediately=args.run_now,
        )
        return 0

    if not args.run_now and not args.feedback:
        args.run_now = True
        print("No flags passed; running one brief. Add --demo for sample data.")

    if args.run_now:
        run_once(args, memory)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
