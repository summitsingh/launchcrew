"""Bounded live Meta proof harness, in-process, no public listener.

AWS build plus RDS plus Spark proof runs as a private ECS one-off using the
exact deployed API image digest and the actual RDS runtime identity. SAM host
route proof runs host-local via the actual photo route plus private DB direct
to Meta with the exact approved JPEG. The public HTTPS browser flow is
separate. Public video image is withheld. No AWS photo asset transfer occurs:
the original photo approval covers only a Meta upload, not a copy to S3, ECR,
CloudWatch, or ECS overrides.

Spark proof is exactly one pipeline with three stages and at most three total
HTTP attempts including failures, with durable decrement before send. Fixed
Standard muse-spark-1.3, exact https origin plus chat path,
max_completion_tokens 2048, n 1, serialized body at most 32 KiB, no Wonder,
no tools, no redirects, no retries. Keys are never logged. Validation needs
actual per call success plus numeric usage and provenance plus stored
spark_calls 3, wonder 0, and empty errors. spark_mode alone means only at
least one success, so all three are checked. Uncertainty latches durably with
no automatic resend. Planning assumes a conservative full model context
ceiling of 3.958272 USD, separate from SAM 1 USD. The byte bound is not a
verified tokenizer count. Model errors are honest failure, never mocked.

SAM proof is one Files upload with Accept JSON plus at most one SSE
segmentation only after valid upload success, using existing credits, no
retry, no new payment, no new key. The Files body carries expires_after
anchor created_at plus 3600 seconds before the final file part. Upload
metadata needs integer (not bool) created_at and expires_at with an exact
3600 difference plus a valid file id before segmentation. Missing or invalid
metadata ends terminal with budget spent, no retry, and no third DELETE
cleanup. Original exact bytes are kept, no image editing. Published SAM price
seen as 0.0025 per image; a Files upload or storage fee free statement was
not found, so no all free claim is made and no hard provider cap is claimed.
Root verifies actual current primary price and operation bound before any
live call. Approval already covers the exact asset with one upload plus at
most one segmentation on existing credits. Finally SAM is disabled with
budget 0 regardless of success, and the keyed private proof process ends.

Public site Meta key is never injected absent a global spend guard. The
public API remains keyless. Pixel-free SAM receipts may feed a private jacket
test clearly labelled for video, with no raw photo, canvas, picker, provider
ids, or digest in public source or logs. Any provider ambiguity ends with no
automatic retry or resend.

Defaults encode private DB, asset bound, limits, and latch, not an arbitrary
target budget. No live HTTP occurs without explicit --live. No host port is
bound here; all proof uses in-process ASGI via TestClient with the real
routes, adapter, pipeline, and persisted receipts. No implicit DDL runs;
proof uses synthetic fictional rows in the existing migrated schema.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

SPARK_PLANNING_USD = 3.958272
SAM_PLANNING_USD = 1.0

_SYNTHETIC_IDEA = ('Proof fictional demo for bounded live test. No real user data. '
                   'Synthetic fictional product for receipt validation only.')
_SEEDED_IDEA = ('Proof fictional seeded demo for deterministic veto check. '
                'No real user data. Seeded claim must stay blocked.')


def default_latch_path(kind):
    root = Path(__file__).resolve().parents[1]
    name = 'meta-proof-%s-latch.json' % ('spark' if kind == 'spark' else 'sam')
    override = os.environ.get('LAUNCHCREW_PROOF_LATCH_FILE', '').strip()
    if override:
        return Path(override)
    local_dir = root / '.local'
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return local_dir / name


def _has_key():
    return bool(os.environ.get('META_API_KEY', '').strip())


def _config_report():
    from launchcrew import spark as spark_module
    lines = []
    lines.append('Key present' if _has_key() else 'Key missing')
    lines.append('Proof model fixed: ' + spark_module.PROOF_MODEL)
    lines.append('Proof origin fixed: ' + spark_module.PROOF_ORIGIN)
    lines.append('Proof chat path fixed: ' + spark_module.PROOF_CHAT_PATH)
    lines.append('Proof output bound: max_completion_tokens %d, n %d, body at most %d bytes'
                 % (spark_module.PROOF_MAX_COMPLETION_TOKENS, spark_module.PROOF_N,
                    spark_module.PROOF_MAX_BODY_BYTES))
    lines.append('Proof attempts max total: %d' % spark_module.PROOF_MAX_ATTEMPTS)
    lines.append('Spark planning ceiling %.6f USD, SAM planning %.2f USD, byte bound not tokenizer verified'
                 % (SPARK_PLANNING_USD, SAM_PLANNING_USD))
    lines.append('SAM expiry: anchor created_at plus 3600 seconds, strict integer validation')
    lines.append('No live HTTP without explicit --live. No port binding in this harness.')
    lines.append('Spark proof runs in private ECS one-off; SAM proof runs host-local; public HTTPS flow separate.')
    return '\n'.join(lines)


def _check_spark_env():
    from launchcrew import spark as spark_module
    if not _has_key():
        return False, 'missing key'
    model = os.environ.get('META_MODEL', '').strip()
    if model and model != spark_module.PROOF_MODEL:
        return False, 'META_MODEL override refused for proof'
    base = os.environ.get('META_API_BASE_URL', '').strip()
    if base and base.rstrip('/') != spark_module.PROOF_ORIGIN:
        return False, 'META_API_BASE_URL override refused for proof'
    if os.environ.get('META_WONDER_MODEL', '').strip():
        return False, 'Wonder refused for proof'
    return True, ''


def _validate_spark_receipt(receipt, per_call):
    if not isinstance(receipt, dict):
        return False, 'receipt shape invalid'
    usage = receipt.get('model_usage', {})
    if not isinstance(usage, dict):
        return False, 'usage missing'
    if usage.get('spark_calls') != 3:
        return False, 'spark_calls is not 3'
    if usage.get('wonder_attempts', 0) != 0 or usage.get('wonder_used', False):
        return False, 'wonder must be zero'
    if usage.get('error_types', []) != []:
        return False, 'errors must be empty'
    if usage.get('spark_mode') != 'spark':
        return False, 'spark_mode is not spark'
    if usage.get('model_used') != 'muse-spark-1.3':
        return False, 'model_used mismatch'
    if usage.get('models_used', []) != ['muse-spark-1.3']:
        return False, 'models_used mismatch'
    if usage.get('tokens_known') is not True:
        return False, 'tokens_known is not true'
    counts = usage.get('token_counts', {})
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        value = counts.get(name)
        if type(value) is not int or value < 0:
            return False, 'token count invalid: ' + name
    if usage.get('request_provider') != 'meta':
        return False, 'request_provider is not meta'
    if usage.get('data_mode') != 'standard_no_train':
        return False, 'data_mode is not standard_no_train'
    if usage.get('data_basis') != 'v2':
        return False, 'data_basis is not v2'
    if not isinstance(per_call, list) or len(per_call) != 3:
        return False, 'per call records need exactly 3'
    for entry in per_call:
        if not isinstance(entry, dict) or entry.get('mode') != 'spark':
            return False, 'per call mode is not spark'
        entry_usage = entry.get('usage', {})
        total = entry_usage.get('total_tokens')
        if type(total) is not int or total < 0:
            return False, 'per call usage invalid'
        if entry.get('request_provider') != 'meta':
            return False, 'per call provider is not meta'
    return True, ''


def run_spark_proof(*, latch_path):
    from fastapi.testclient import TestClient
    from launchcrew import spark as spark_module
    from backend.app import app
    ok, reason = _check_spark_env()
    if not ok:
        print('Spark proof refused: ' + reason)
        return 1
    try:
        spark_module.init_proof_latch(latch_path)
    except Exception as error:
        print('Spark proof latch refused: ' + type(error).__name__)
        return 1
    per_call = []
    real_call = spark_module._call
    real_urlopen = spark_module.urlopen
    http_count = {'total': 0}

    class _LiveProofResponse:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._inner.__exit__(exc_type, exc, tb)

        def read(self, *args, **kwargs):
            try:
                return self._inner.read(*args, **kwargs)
            except Exception as error:
                name = type(error).__name__
                if name in ('TimeoutError', 'URLError', 'HTTPError', 'ConnectionError',
                            'RemoteDisconnected', 'SSLError', 'SocketTimeout',
                            'IncompleteRead', 'ConnectionResetError', 'BrokenPipeError'):
                    try:
                        spark_module.latch_proof_uncertain(latch_path)
                    except Exception:
                        pass
                raise

        def __iter__(self):
            try:
                for chunk in self._inner:
                    yield chunk
            except Exception as error:
                name = type(error).__name__
                if name in ('TimeoutError', 'URLError', 'HTTPError', 'ConnectionError',
                            'RemoteDisconnected', 'SSLError', 'SocketTimeout',
                            'IncompleteRead', 'ConnectionResetError', 'BrokenPipeError'):
                    try:
                        spark_module.latch_proof_uncertain(latch_path)
                    except Exception:
                        pass
                raise

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def proof_open(request, timeout=None):
        spark_module.validate_proof_request(request)
        spark_module.claim_proof_attempt(latch_path)
        http_count['total'] += 1
        try:
            inner = spark_module._spark_opener().open(request, timeout=timeout)
        except Exception as error:
            name = type(error).__name__
            if name in ('TimeoutError', 'URLError', 'HTTPError', 'ConnectionError',
                        'RemoteDisconnected', 'SSLError', 'SocketTimeout',
                        'IncompleteRead', 'ConnectionResetError', 'BrokenPipeError'):
                try:
                    spark_module.latch_proof_uncertain(latch_path)
                except Exception:
                    pass
            raise
        return _LiveProofResponse(inner)

    def recording_call(system_prompt, user_prompt, schema_hint, model):
        if model != spark_module.PROOF_MODEL:
            result = {'mode': 'deterministic_fallback', 'model_used': 'none',
                      'attempted': True, 'attempted_model': model,
                      'error_type': 'ValueError', 'usage': {},
                      'request_provider': 'meta'}
            per_call.append(result)
            return result
        spark_module.urlopen = proof_open
        try:
            result = real_call(system_prompt, user_prompt, schema_hint, model)
        finally:
            spark_module.urlopen = real_urlopen
        per_call.append(dict(result))
        return result

    original_call = spark_module._call
    spark_module._call = recording_call
    saved_key = os.environ.get('META_API_KEY', '')
    receipt = None
    run_id = ''
    try:
        with TestClient(app) as client:
            response = client.post('/api/runs', json={
                'idea': _SYNTHETIC_IDEA, 'agent_name': 'Maker',
                'checker_profile': 'standard'})
            if response.status_code != 201:
                print('Spark proof run create failed: HTTP ' + str(response.status_code))
                return 1
            receipt = response.json()
            run_id = receipt.get('run_id', '')
            if http_count['total'] > spark_module.PROOF_MAX_ATTEMPTS:
                print('Spark proof exceeded max total HTTP attempts')
                return 1
            ok, reason = _validate_spark_receipt(receipt, per_call)
            if not ok:
                print('Spark proof receipt invalid: ' + reason)
                return 1
            readback = client.get('/api/runs/%s/receipt' % run_id)
            if readback.status_code != 200:
                print('Spark proof receipt readback failed')
                return 1
            stored = readback.json()
            if stored.get('model_usage', {}).get('spark_calls') != 3:
                print('Spark proof stored receipt mismatch')
                return 1
            os.environ.pop('META_API_KEY', None)
            try:
                seeded = client.post('/api/runs', json={
                    'idea': _SEEDED_IDEA, 'agent_name': 'Maker',
                    'seed_unverified_claim': True, 'checker_profile': 'standard'})
                if seeded.status_code != 201:
                    print('Seeded veto run failed: HTTP ' + str(seeded.status_code))
                    return 1
                seeded_receipt = seeded.json()
                if seeded_receipt.get('checker_v1', {}).get('blocked_count', 0) < 1:
                    print('Seeded veto missing expected block')
                    return 1
                if seeded_receipt.get('model_usage', {}).get('spark_calls', 0) != 0:
                    print('Seeded phase must use zero model HTTP')
                    return 1
                seeded_id = seeded_receipt.get('run_id', '')
                revision = seeded_receipt.get('revision', 0)
                revised = client.post('/api/runs/%s/revise' % seeded_id, json={
                    'post': 'Proof fictional revised post for veto demo.',
                    'email': 'Proof fictional revised email for veto demo.',
                    'base_revision': revision})
                if revised.status_code != 200:
                    print('Revision failed: HTTP ' + str(revised.status_code))
                    return 1
                approved = client.post('/api/runs/%s/approve' % seeded_id, json={})
                if approved.status_code != 200:
                    print('Approval failed: HTTP ' + str(approved.status_code))
                    return 1
                exported = client.post('/api/runs/%s/export' % seeded_id, json={})
                if exported.status_code != 200:
                    print('Export failed: HTTP ' + str(exported.status_code))
                    return 1
                final = client.get('/api/runs/%s/receipt' % seeded_id)
                if final.status_code != 200:
                    print('Final readback failed')
                    return 1
            finally:
                if saved_key:
                    os.environ['META_API_KEY'] = saved_key
            if http_count['total'] != 3:
                print('Spark proof needs exactly 3 total HTTP attempts')
                return 1
            state = spark_module.read_proof_latch(latch_path)
            if state.get('attempts_used') != 3 or state.get('uncertain'):
                print('Spark proof latch state invalid')
                return 1
            usage = receipt.get('model_usage', {})
            counts = usage.get('token_counts', {})
            print('SPARK PROOF PASS spark_calls 3 wonder 0 errors 0')
            print('prompt_tokens: ' + str(counts.get('prompt_tokens', 0)))
            print('completion_tokens: ' + str(counts.get('completion_tokens', 0)))
            print('total_tokens: ' + str(counts.get('total_tokens', 0)))
            print('data_mode: standard_no_train provider: meta basis: v2')
            return 0
    except spark_module.ProofLatchError as error:
        print('Spark proof latch error: ' + type(error).__name__)
        return 1
    except Exception as error:
        print('Spark proof failed: ' + type(error).__name__)
        try:
            spark_module.latch_proof_uncertain(latch_path)
        except Exception:
            pass
        return 1
    finally:
        spark_module._call = original_call
        spark_module.urlopen = real_urlopen
        if saved_key and not os.environ.get('META_API_KEY', ''):
            os.environ['META_API_KEY'] = saved_key


def _check_sam_env():
    if not _has_key():
        return False, 'missing key'
    if os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED', '').strip().lower() != 'true':
        return False, 'SAM not enabled'
    base = os.environ.get('META_API_BASE_URL', '').strip()
    if base and base.rstrip('/') != 'https://api.meta.ai/v1':
        return False, 'META_API_BASE_URL override refused for proof'
    if not os.environ.get('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', '').strip():
        return False, 'approved digest list missing'
    photo_path = os.environ.get('LAUNCHCREW_PROOF_PHOTO_PATH', '').strip()
    if not photo_path:
        return False, 'proof photo path missing'
    return True, ''


def _approved_digest_set():
    raw = os.environ.get('LAUNCHCREW_PHOTO_APPROVED_DIGESTS', '')
    return {part.strip().lower() for part in raw.split(',') if part.strip()}


def _reserve_sam_latch(latch_path):
    target = Path(latch_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        if target.exists():
            return False
        return False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps({'label': 'meta-proof-sam', 'used': True}) + '\n')
    except OSError:
        try:
            target.unlink()
        except OSError:
            pass
        return False
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return True


def run_sam_proof(*, latch_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from backend import sam as sam_module
    from backend import store as store_module
    from backend.app import app
    if os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED', '').strip().lower() != 'true':
        ok, reason = _check_sam_env()
        print('SAM proof refused: ' + (reason if not ok else 'SAM not enabled'))
        return 1
    original_upload = sam_module.upload_and_segment
    saved_key = os.environ.get('META_API_KEY', '')
    cleanup_status = {'budget_zero_failed': False}
    sam_counts = {'uploads': 0, 'segmentations': 0}
    candidate = None
    try:
        ok, reason = _check_sam_env()
        if not ok:
            print('SAM proof refused: ' + reason)
            return 1
        if not _reserve_sam_latch(latch_path):
            print('SAM proof latch refused: reuse refused')
            return 1
        photo_path = os.environ.get('LAUNCHCREW_PROOF_PHOTO_PATH', '').strip()
        try:
            raw_bytes = Path(photo_path).read_bytes()
        except Exception:
            print('SAM proof photo read failed')
            return 1
        digest = hashlib.sha256(raw_bytes).hexdigest().lower()
        if digest not in _approved_digest_set():
            print('SAM proof approved identity mismatch')
            return 1
        print('SAM proof approved identity validated')
        if raw_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
            kind = 'png'
        elif raw_bytes.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
            kind = 'jpeg'
        else:
            print('SAM proof photo is not PNG or JPEG')
            return 1
        data_uri = 'data:image/%s;base64,' % kind + base64.b64encode(raw_bytes).decode('ascii')
        try:
            with store_module.engine().begin() as connection:
                connection.execute(text("UPDATE sam_budget SET remaining_images=1 WHERE id='global'"))
        except Exception as error:
            print('SAM proof budget grant failed: ' + type(error).__name__)
            return 1

        def proof_upload(raw, mime_arg, concept='product', timeout_s=30.0):
            check = hashlib.sha256(raw).hexdigest().lower()
            if check not in _approved_digest_set():
                raise sam_module.SamTransportError('digest mismatch')
            try:
                records = original_upload(raw, mime_arg, concept='jacket', timeout_s=timeout_s)
            except sam_module.SamTransportError as error:
                try:
                    sam_counts['uploads'] = int(getattr(error, 'uploads', 0) or 0)
                except (TypeError, ValueError):
                    sam_counts['uploads'] = 0
                try:
                    sam_counts['segmentations'] = int(getattr(error, 'segmentations', 0) or 0)
                except (TypeError, ValueError):
                    sam_counts['segmentations'] = 0
                raise
            sam_counts['uploads'] = 1
            sam_counts['segmentations'] = 1
            return records

        sam_module.upload_and_segment = proof_upload
        try:
            with TestClient(app) as client:
                os.environ.pop('META_API_KEY', None)
                try:
                    created = client.post('/api/runs', json={
                        'idea': _SYNTHETIC_IDEA, 'agent_name': 'Maker'})
                finally:
                    if saved_key:
                        os.environ['META_API_KEY'] = saved_key
                if created.status_code != 201:
                    print('SAM proof run create failed: HTTP ' + str(created.status_code))
                    return 1
                run_id = created.json().get('run_id', '')
                response = client.post('/api/runs/%s/photo-check' % run_id, json={
                    'image_data_uri': data_uri, 'expected_revision': 0})
                if response.status_code not in (200, 422, 409):
                    print('SAM proof photo check HTTP ' + str(response.status_code))
                    return 1
                body = response.json() if response.status_code == 200 else {}
                receipt = body.get('receipt', {}) if isinstance(body, dict) else {}
                with store_module.engine().begin() as connection:
                    budget = connection.execute(
                        text("SELECT remaining_images FROM sam_budget WHERE id='global'")).scalar()
                    row = connection.execute(
                        text('SELECT status, label, reason FROM sam_calls WHERE run_id=:id AND revision=0'),
                        {'id': run_id}).mappings().first()
                if response.status_code != 200:
                    print('SAM proof photo check refused: HTTP ' + str(response.status_code))
                    return 1
                if budget != 0:
                    print('SAM proof budget not spent')
                    return 1
                if row is None or row['status'] not in ('succeeded', 'failed_terminal'):
                    print('SAM proof ledger not terminal')
                    return 1
                if row['status'] != 'succeeded':
                    print('SAM proof ended terminal without success')
                    return 1
                if sam_counts['uploads'] != 1 or sam_counts['segmentations'] != 1:
                    print('SAM proof attempt counts invalid')
                    return 1
                photo_status = receipt.get('photo_status', {}) if isinstance(receipt, dict) else {}
                if photo_status.get('state') not in ('checked',):
                    print('SAM proof receipt photo state invalid')
                    return 1
                candidate = {'run_id': run_id, 'label': row['label'],
                             'uploads': sam_counts['uploads'],
                             'segmentations': sam_counts['segmentations']}
        except sam_module.SamTransportError as error:
            print('SAM proof transport failed: ' + type(error).__name__)
            return 1
        except Exception as error:
            print('SAM proof failed: ' + type(error).__name__)
            return 1
    except sam_module.SamTransportError as error:
        print('SAM proof transport failed: ' + type(error).__name__)
        return 1
    except Exception as error:
        print('SAM proof failed: ' + type(error).__name__)
        return 1
    finally:
        try:
            sam_module.upload_and_segment = original_upload
        except Exception:
            pass
        os.environ['LAUNCHCREW_PHOTO_SAM_ENABLED'] = 'false'
        try:
            with store_module.engine().begin() as connection:
                connection.execute(text("UPDATE sam_budget SET remaining_images=0 WHERE id='global'"))
        except Exception:
            cleanup_status['budget_zero_failed'] = True
        if saved_key and not os.environ.get('META_API_KEY', ''):
            os.environ['META_API_KEY'] = saved_key
    if candidate is None:
        return 1
    if cleanup_status['budget_zero_failed']:
        print('SAM proof cleanup failed; no PASS')
        return 1
    if os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED', '').strip().lower() != 'false':
        print('SAM proof cleanup failed; SAM still enabled')
        return 1
    try:
        with store_module.engine().begin() as connection:
            final_budget = connection.execute(
                text("SELECT remaining_images FROM sam_budget WHERE id='global'")).scalar()
            final_row = connection.execute(
                text('SELECT status, label FROM sam_calls WHERE run_id=:id AND revision=0'),
                {'id': candidate['run_id']}).mappings().first()
    except Exception:
        print('SAM proof readback failed; no PASS')
        return 1
    if final_budget != 0:
        print('SAM proof budget readback not zero; no PASS')
        return 1
    if final_row is None or final_row['status'] != 'succeeded':
        print('SAM proof ledger readback not terminal success; no PASS')
        return 1
    if candidate['uploads'] != 1 or candidate['segmentations'] != 1:
        print('SAM proof counts readback invalid; no PASS')
        return 1
    print('SAM PROOF PASS uploads 1 segmentations 1 label ' + str(final_row['label'] or 'none'))
    print('method: sam-3.1 expiry: created_at plus 3600')
    print('ledger: terminal budget spent no retry no delete cleanup')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bounded live Meta proof, no port binding.')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--mode', choices=['spark', 'sam', 'all'], default='sam')
    parser.add_argument('--latch-file', default='')
    args = parser.parse_args(argv)
    if not args.live:
        print(_config_report())
        print('No network call made. Explicit --live is required.')
        return 0
    if args.mode in ('spark', 'all'):
        latch = Path(args.latch_file) if args.latch_file else default_latch_path('spark')
        code = run_spark_proof(latch_path=latch)
        if code != 0 or args.mode == 'spark':
            return code
    if args.mode in ('sam', 'all'):
        latch = default_latch_path('sam')
        return run_sam_proof(latch_path=latch)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

