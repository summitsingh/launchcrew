"""Reuse v1 agents, pipeline, and receipt gates without new run JSON files."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from launchcrew import agents, run, receipts
from backend.sam import verify_configured_demo

ROOT = Path(__file__).resolve().parents[1]


def preview(profile, idea):
    # Existing preview has no model calls. Temporary profile writes are avoided here.
    agents.validate(profile)
    return {'dry_run': True, 'profile': profile, 'sample_idea': idea,
            'first_action': 'Read facts_file, apply decision_rules, and prepare a draft for approval.',
            'model_called': False, 'side_effects': False}


def execute(run_id, idea, profile, seed):
    captured = []
    (ROOT / '.local').mkdir(exist_ok=True)
    with TemporaryDirectory(dir=ROOT / '.local') as directory:
        for name in ('Scout', 'Maker', 'Checker'):
            agents.save_agent(agents.load_agent(name, ROOT / 'agents'), directory)
        maker = copy.deepcopy(profile)
        maker['name'] = 'Maker'
        agents.save_agent(maker, directory)
        try:
            run.run_pipeline(idea, ROOT / 'facts/demo_facts.json', directory, run_id,
                             seed_unverified_claim=seed, model_enabled=True,
                             visual_verifier=verify_configured_demo,
                             receipt_writer=lambda receipt, path: captured.append(receipt))
        except Exception:
            if not captured:
                raise
    return captured[0]


def export_pack(receipt):
    # Keep v1 export validation and serialization semantics.
    (ROOT / '.local').mkdir(exist_ok=True)
    with TemporaryDirectory(dir=ROOT / '.local') as directory:
        path = receipts.export_receipt(receipt, Path(directory) / 'pack.json')
        return path.read_bytes()
