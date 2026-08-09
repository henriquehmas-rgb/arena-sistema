async def test_client_fixture_sobe_app(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200


async def test_fixtures_de_login_criam_usuarios(cliente_logado, staff_admin_logado):
    assert cliente_logado["cliente"].id is not None
    assert "Authorization" in cliente_logado["headers"]
    assert staff_admin_logado["staff"].id is not None
    assert "Authorization" in staff_admin_logado["headers"]
