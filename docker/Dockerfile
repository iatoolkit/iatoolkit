# syntax=docker/dockerfile:1
FROM python:3.13.15-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /opt/app
COPY pyproject.toml uv.lock readme.md LICENSE ./
COPY src/iatoolkit ./src/iatoolkit
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.13.15-slim-trixie
ENV PATH="/opt/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FLASK_SKIP_DOTENV=1 IATOOLKIT_DATA_DIR=/var/lib/iatoolkit \
    IATOOLKIT_DEMO_ROOT=/opt/demo-resources
RUN groupadd --gid 10001 iatoolkit \
    && useradd --uid 10001 --gid 10001 --create-home iatoolkit \
    && mkdir -p /var/lib/iatoolkit/storage \
    && chown -R iatoolkit:iatoolkit /var/lib/iatoolkit
COPY --from=build /opt/app/.venv /opt/app/.venv
COPY companies/sample_company/config/help_content.yaml companies/sample_company/config/onboarding_cards.yaml /opt/demo-resources/config/
COPY companies/sample_company/prompts/ /opt/demo-resources/prompts/
COPY companies/sample_company/context/ /opt/demo-resources/context/
COPY companies/sample_company/templates/ /opt/demo-resources/templates/
COPY companies/sample_company/sample_data/employee_contracts/ /opt/demo-resources/sample_data/employee_contracts/
COPY companies/sample_company/sample_data/supplier_manuals/ /opt/demo-resources/sample_data/supplier_manuals/
COPY docker/ /opt/distribution/
COPY docker/demo/company.yaml /opt/demo-resources/config/company.yaml
WORKDIR /opt
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "/opt/distribution/entrypoint.py"]
CMD ["gunicorn", "--config", "/opt/distribution/gunicorn.conf.py", "distribution.app:create_app()"]

# Release metadata comes from the same version as the installed Python package.
# Keep it last so metadata changes do not invalidate the dependency layer.
ARG VERSION=dev
LABEL org.opencontainers.image.source="https://github.com/iatoolkit/iatoolkit" \
      org.opencontainers.image.description="IAToolkit Community with Sample Company and Northwind" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version=$VERSION
RUN python -c 'from importlib.metadata import version; import sys; assert sys.argv[1] == "dev" or sys.argv[1] == version("iatoolkit"), "Container tag and package version differ"' "$VERSION"
