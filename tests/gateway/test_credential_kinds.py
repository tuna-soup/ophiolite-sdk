"""Application consent cannot silently become an upload delegate."""
import pytest
from test_in_process_publish import web,shared,app,service,client
from ophiolite.errors import PermissionRefused


def test_upload_requires_explicit_delegate(web,tmp_path):
    from project_gateway.tests.test_applications import LAS
    grant=client(web,'alice','grant')
    with pytest.raises(PermissionRefused):
        grant.work_folder(tmp_path/'denied').upload_las(LAS.encode(),name='Denied',attribution='Original synthetic fixture',audience=['alice'],rights_confirmed=True)
    delegate=client(web,'alice','delegate')
    upload=delegate.work_folder(tmp_path/'allowed').upload_las(LAS.encode(),name='Allowed',attribution='Original synthetic fixture',audience=['alice'],rights_confirmed=True)
    assert upload.revision
