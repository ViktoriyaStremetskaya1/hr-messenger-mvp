async def test_login_logout_me(anon, users):
    r = await anon.get("/api/auth/me")
    assert r.status_code == 401
    r = await anon.post("/api/auth/login", json={"login": "ADMIN", "password": "Passw0rd!"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert "hr_session" in r.cookies
    assert (await anon.get("/api/auth/me")).json()["login"] == "admin"
    await anon.post("/api/auth/logout")
    anon.cookies.clear()
    assert (await anon.get("/api/auth/me")).status_code == 401


async def test_wrong_password_is_audited(anon, admin):
    r = await anon.post("/api/auth/login", json={"login": "admin", "password": "nope"})
    assert r.status_code == 401
    log = (await admin.get("/api/audit", params={"action": "auth.login_failed"})).json()
    assert log["total"] == 1


async def test_only_admin_manages_users(admin, recruiter):
    payload = {"login": "new.rec", "full_name": "Новый", "role": "recruiter", "password": "Secret123!"}
    assert (await recruiter.post("/api/users", json=payload)).status_code == 403
    r = await admin.post("/api/users", json=payload)
    assert r.status_code == 201
    assert (await admin.post("/api/users", json=payload)).status_code == 409
    uid = r.json()["id"]
    r = await admin.patch(f"/api/users/{uid}", json={"is_active": False})
    assert r.json()["is_active"] is False


async def test_disabled_user_cannot_login(admin, anon):
    r = await admin.post("/api/users", json={"login": "x11", "full_name": "X", "role": "recruiter", "password": "Secret123!"})
    await admin.patch(f"/api/users/{r.json()['id']}", json={"is_active": False})
    assert (await anon.post("/api/auth/login", json={"login": "x11", "password": "Secret123!"})).status_code == 401


async def test_admin_cannot_lock_self(admin, users):
    r = await admin.patch(f"/api/users/{users['admin'].id}", json={"role": "recruiter"})
    assert r.status_code == 400


async def test_settings_and_roles(admin, recruiter):
    s = (await recruiter.get("/api/settings")).json()
    assert s["working_hours"]["start"] == "09:00"
    assert s["touch_frequency_days"] == 3
    assert (await recruiter.patch("/api/settings", json={"touch_frequency_days": 5})).status_code == 403
    r = await admin.patch("/api/settings", json={"touch_frequency_days": 5})
    assert r.json()["touch_frequency_days"] == 5
    assert (await admin.patch("/api/settings", json={"bogus": 1})).status_code == 400
    assert (await recruiter.get("/api/audit")).status_code == 403
