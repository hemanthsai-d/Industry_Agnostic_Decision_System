# Free Tooling Plan (Local-First)

This platform already includes:
1. FastAPI app + MCP server code.
2. Local Docker services for Postgres, Redis, and optional OPA.

## Recommended free stack for next steps

1. Policy engine: OPA (already wired as optional).
2. Workflow/orchestration: Temporal OSS.
3. Feature flags: Unleash OSS.
4. IaC: OpenTofu.
5. Security scanning: Trivy.
6. LLM traces/evals: Langfuse self-host + Ragas + Evidently OSS.

## Local install starting points

Temporal OSS:
```bash
brew install temporal
temporal server start-dev
```

Unleash OSS:
```bash
docker run -d --name unleash -p 4242:4242 unleashorg/unleash-server
```

Trivy:
```bash
brew install trivy
trivy fs .
```

OpenTofu:
```bash
brew install opentofu
tofu version
```

## Adoption order

1. Start with OPA + current app.
2. Add Temporal for handoff/retry workflows.
3. Add Unleash for safe rollouts.
4. Add Langfuse/Ragas/Evidently for evaluation loop.

