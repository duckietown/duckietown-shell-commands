import os


def get_asset_dir(asset: str):
    script_files = os.path.dirname(os.path.realpath(__file__))
    asset_path = os.path.join(script_files, '..', 'assets', asset)
    if not os.path.exists(asset_path):
        msg = "Could not find asset '%s'" % asset_path
        raise Exception(msg)
    return asset_path
