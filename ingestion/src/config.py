import os
from dotenv import load_dotenv, find_dotenv
import tempfile
from pathlib import Path

# Cargar variables de entorno desde el .env más cercano (buscando hacia arriba)
load_dotenv(find_dotenv())

# Raíz del proyecto (sube tres niveles: src -> ingestion -> nautiq)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY")
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"


class ConfigProvider:
    def __init__(self):
        self.env = os.getenv("APP_ENV", "local")
        self._temp_dir = None  # Mantendrá vivo el directorio temporal en producción

    def get_kafka_certs(self) -> dict:
        """Devuelve un diccionario con las rutas a los certificados."""

        # 1. MODO LOCAL: El desarrollador tiene los archivos en su máquina
        if self.env == "local":
            return {
                "ca": os.getenv("KAFKA_CA_PATH", str(PROJECT_ROOT / ".certs" / "ca.pem")),
                "cert": os.getenv("KAFKA_CERT_PATH", str(PROJECT_ROOT / ".certs" / "service.cert")),
                "key": os.getenv("KAFKA_KEY_PATH", str(PROJECT_ROOT / ".certs" / "service.key")),
            }

        # 2. MODO PRODUCCIÓN: Extraer de OCI Vault e inyectar en archivos temporales
        elif self.env == "production":
            if not self._temp_dir:
                self._temp_dir = tempfile.TemporaryDirectory()

            ca_path = os.path.join(self._temp_dir.name, "ca.pem")
            cert_path = os.path.join(self._temp_dir.name, "service.cert")
            key_path = os.path.join(self._temp_dir.name, "service.key")

            # Escribir los secretos en el directorio temporal
            with open(ca_path, "w") as f:
                f.write(self._fetch_oci_secret(os.getenv("OCI_SECRET_ID_CA")))
            with open(cert_path, "w") as f:
                f.write(self._fetch_oci_secret(os.getenv("OCI_SECRET_ID_CERT")))
            with open(key_path, "w") as f:
                f.write(self._fetch_oci_secret(os.getenv("OCI_SECRET_ID_KEY")))

            return {"ca": ca_path, "cert": cert_path, "key": key_path}

    def _fetch_oci_secret(self, secret_id: str) -> str:
        """Lógica interna para hablar con OCI Vault usando Instance Principals."""
        import oci
        import base64

        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        client = oci.secrets.SecretsClient({}, signer=signer)
        response = client.get_secret_bundle(secret_id)
        return base64.b64decode(response.data.secret_bundle_content.content).decode(
            "utf-8"
        )
