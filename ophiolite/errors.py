"""Stable categories and safe messages. Technical context is separate from prose."""
class OphioliteError(ValueError):
    code='sdk-error'
    retryable=False

    def __init__(self,message,recovery='',*,status=None,code=None,details=None,command_id=None,work_folder=None):
        if message=='evidence-inconsistent':
            code=message;message='The reported reader history disagrees with its records.'
        self.code=code or type(self).code
        self.message,self.recovery,self.status=message,recovery,status
        self.details=details or {}
        self.command_id,self.work_folder=command_id,work_folder
        super().__init__(message+(' '+recovery if recovery else ''))

class VerificationFailed(OphioliteError): code='verification-failed'
class AuthenticationRequired(OphioliteError): code='authentication-required'
class PermissionRefused(OphioliteError): code='PERMISSION_DENIED'
class Unavailable(OphioliteError): code='not-found'
class IntegrityConflict(OphioliteError): code='integrity-conflict'
class CapacityExceeded(VerificationFailed): code='capacity-exceeded'
class Incompatible(OphioliteError): code='incompatible-context'
class Refused(OphioliteError): code='INVALID_ARGUMENT'
class ResyncRequired(OphioliteError): code='resync-required'  # E28: the server no longer holds this cursor (CURSOR_EXPIRED)
class AxisMismatch(OphioliteError):
    code='axis-mismatch'

    def __init__(self,curves,reason,first_differing_index=None):
        labels={'values':'depth coordinates','unit':'depth units','reference':'depth references','interpretation':'reader interpretations','source':'exact source versions'}
        self.curves,self.reason,self.first_differing_index=tuple(curves),reason,first_differing_index
        super().__init__('These curves have different '+labels.get(reason,'scientific context')+'.',
                         'Read them separately or align them explicitly; no resampling or unit conversion was performed.',
                         details={'curves':list(curves),'reason':reason,'first_differing_index':first_differing_index})

class MissingExtra(OphioliteError): code='missing-extra'
class InterpretationChanged(VerificationFailed): code='interpretation-changed'
class InterpretationDiffers(UserWarning): pass

class Busy(Unavailable):
    code='busy'
    retryable=True

    def __init__(self,message,recovery='',*,retry_after=0,**kwargs):
        self.retry_after=retry_after
        super().__init__(message,recovery,**kwargs)

class ValidationFailed(Refused):
    code='validation-failed'
    def __init__(self,violations):
        self.violations=tuple(violations)
        super().__init__('Publication inputs need correction. '+' '.join(violations),details={'violations':list(violations)})

class RecoveryUnavailable(Refused):code='recovery-unavailable'
class ShareOutcomeUnknown(Unavailable):code='share-outcome-unknown'
class ImportIncomplete(OphioliteError):code='import-incomplete'
