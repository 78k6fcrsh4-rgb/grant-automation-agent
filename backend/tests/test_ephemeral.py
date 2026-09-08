"""Tests for the forget-by-design behavior: TTL purge, explicit forget, and
startup temp-dir wipe. All offline."""
import os
import time
import tempfile

from app.routes import grant_routes as gr
from app.models.schemas import GrantData


def _mk_grant(fid, tenant=1, created=None):
    gr.grant_data_store[fid] = GrantData(raw_text="x")
    gr.grant_tenant[fid] = tenant
    gr.grant_created_at[fid] = created if created is not None else time.time()


def test_purge_expired_removes_old_grants_and_files():
    fid = "old-1"
    _mk_grant(fid, created=time.time() - (gr.GRANT_TTL_SECONDS + 1000))
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(b"generated doc"); f.close()
    gr.generated_docs_store[fid] = {"summary": f.name}

    gr.purge_expired()

    assert fid not in gr.grant_data_store
    assert fid not in gr.grant_tenant
    assert fid not in gr.grant_created_at
    assert not os.path.exists(f.name), "generated file must be deleted on purge"


def test_touch_prevents_purge():
    fid = "fresh-1"
    _mk_grant(fid, created=time.time() - (gr.GRANT_TTL_SECONDS + 1000))
    gr._touch(fid)  # sliding expiration resets the clock
    gr.purge_expired()
    assert fid in gr.grant_data_store, "recently touched grant must survive purge"
    gr._forget(fid)


def test_forget_removes_everything():
    fid = "f-1"
    _mk_grant(fid)
    f = tempfile.NamedTemporaryFile(delete=False); f.close()
    gr.generated_docs_store[fid] = {"budget": f.name}
    gr._forget(fid)
    assert fid not in gr.grant_data_store
    assert fid not in gr.grant_tenant
    assert fid not in gr.grant_created_at
    assert not os.path.exists(f.name)


def test_clear_temp_dir_wipes_pii_keeps_gitkeep(tmp_path, monkeypatch):
    d = tmp_path / "temp"; d.mkdir()
    (d / ".gitkeep").write_text("")
    (d / "grantee.pdf").write_text("sensitive")
    (d / "out_budget.xlsx").write_text("x")
    # The scratch directory belongs to the working store, not the
    # route module (v2.8.0).
    monkeypatch.setattr(gr.repository, "temp_dir", str(d))
    gr.clear_temp_dir()
    assert (d / ".gitkeep").exists()
    assert not (d / "grantee.pdf").exists()
    assert not (d / "out_budget.xlsx").exists()
