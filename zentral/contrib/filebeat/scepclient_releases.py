import os
import tempfile
import zipfile
import requests
from zentral.utils.local_dir import get_and_create_local_dir

SCEPCLIENT_RELEASE_URL_TMPL = "https://github.com/micromdm/scep/releases/download/v{version}/scep.zip"


def get_scepclient_binary(version="1.0.0", platform="darwin"):
    # release dir
    releases_root = get_and_create_local_dir("scep", "releases")
    release_name = version
    release_dir = os.path.join(releases_root, release_name)
    if os.path.commonpath([releases_root, release_dir]) != releases_root:
        raise ValueError("wrong release name")
    os.makedirs(release_dir, exist_ok=True)

    # binary exists?
    scepclient_binary_path = os.path.join(
        release_dir, f"scepclient-{platform}-amd64"
    )

    if not os.path.exists(scepclient_binary_path):
        # tempfile
        tfh, tfn = tempfile.mkstemp(suffix="scepclient.zip")
        # download release
        download_url = SCEPCLIENT_RELEASE_URL_TMPL.format(version=version)
        resp = requests.get(download_url, stream=True)
        with os.fdopen(tfh, "wb") as tf:
            for chunk in resp.iter_content(chunk_size=64 * 2**10):
                if chunk:
                    tf.write(chunk)
        # extract release
        with zipfile.ZipFile(tfn) as zf:
            binary_names = [
                name
                for name in zf.namelist()
                if "scepclient-" in name and "-amd64" in name
            ]

            for binary_name in binary_names:
                local_binary_path = os.path.join(release_dir, os.path.basename(binary_name))
                ibf = zf.open(binary_name)
                with open(local_binary_path, "wb") as obf:
                    while True:
                        if chunk := ibf.read(64 * 2**10):
                            obf.write(chunk)
                        else:
                            break
                    ibf.close()
    os.chmod(scepclient_binary_path, 0o755)
    return scepclient_binary_path
