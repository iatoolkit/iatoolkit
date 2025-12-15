from iatoolkit.common.asset_storage import AssetRepository, AssetType
from pathlib import Path


class FileSystemAssetRepository(AssetRepository):
    def _get_path(self, company_short_name: str, asset_type: AssetType, filename: str = "") -> Path:
        return Path("companies") / company_short_name / asset_type.value / filename

    def exists(self, company_short_name: str, asset_type: AssetType, filename: str) -> bool:
        return self._get_path(company_short_name, asset_type, filename).is_file()

    def read_text(self, company_short_name: str, asset_type: AssetType, filename: str) -> str:
        path = self._get_path(company_short_name, asset_type, filename)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return path.read_text(encoding="utf-8")

    def list_files(self, company_short_name: str, asset_type: AssetType, extension: str = None) -> list[str]:
        directory = self._get_path(company_short_name, asset_type)
        if not directory.exists():
            return []
        files = [f.name for f in directory.iterdir() if f.is_file()]
        if extension:
            files = [f for f in files if f.endswith(extension)]
        return files

    def write_text(self, company_short_name: str, asset_type: AssetType, filename: str, content: str) -> None:
        path = self._get_path(company_short_name, asset_type, filename)
        # Ensure the directory exists (e.g. creating a new company structure)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete(self, company_short_name: str, asset_type: AssetType, filename: str) -> None:
        path = self._get_path(company_short_name, asset_type, filename)
        if path.exists():
            path.unlink()