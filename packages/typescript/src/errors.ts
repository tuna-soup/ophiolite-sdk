export class OphioliteError extends Error {
  constructor(message: string, public readonly code = "sdk-error", public readonly recovery = "", public readonly status?: number) {
    super(message + (recovery ? " " + recovery : "")); this.name = new.target.name;
  }
}
export class VerificationFailed extends OphioliteError {
  constructor(message = "Scientific data does not satisfy the declared contract.") { super(message, "verification-failed", "No data was accepted."); }
}
export class Incompatible extends OphioliteError {
  constructor() { super("The saved and current readers use different mappings.", "incompatible-context", "Read the exact artifact instead."); }
}
export class AuthenticationRequired extends OphioliteError {
  constructor(status = 401) { super("Authentication is required.", "authentication-required", "Sign in again.", status); }
}
export class PermissionRefused extends OphioliteError {
  constructor(status = 403) { super("Access was refused.", "PERMISSION_DENIED", "Ask the owner to check your access.", status); }
}
export class Unavailable extends OphioliteError {
  constructor(status?: number) { super("The requested data is unavailable.", "not-found", "Check the exact revision and service access.", status); }
}
export class IntegrityConflict extends OphioliteError {
  constructor(status = 409) { super("The operation conflicts with the saved state.", "integrity-conflict", "Read the current state before continuing.", status); }
}
export class CapacityExceeded extends OphioliteError {
  constructor(status = 413) { super("The supported size was exceeded.", "capacity-exceeded", "Use a smaller supported input.", status); }
}
export class Refused extends OphioliteError {
  constructor(status = 400) { super("The request was refused.", "INVALID_ARGUMENT", "Check the request fields.", status); }
}
export class Busy extends OphioliteError {
  constructor(status = 503) { super("The service is busy.", "busy", "Try again later.", status); }
}
export class ShareOutcomeUnknown extends OphioliteError {
  constructor() { super("The sharing response did not complete.", "share-outcome-unknown", "Read the current grants before deciding whether to share again."); }
}
export function httpError(status: number): OphioliteError {
  if (status === 401) return new AuthenticationRequired(status);
  if (status === 403) return new PermissionRefused(status);
  if (status === 409) return new IntegrityConflict(status);
  if (status === 413) return new CapacityExceeded(status);
  if (status === 429 || status === 503) return new Busy(status);
  if (status === 400 || status === 422) return new Refused(status);
  return new Unavailable(status);
}
