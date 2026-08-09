from fastapi import FastAPI

# NOTA: scaffold mínimo (Task T1). A configuração completa (CORS, routers,
# scheduler de jobs, healthcheck) é responsabilidade da Task T3 (Wave 0).
app = FastAPI(title="Arena Cacerense API")
