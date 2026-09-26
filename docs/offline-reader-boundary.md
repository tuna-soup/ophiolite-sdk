# Local validation and the future offline reader

Models, the contract snapshot and validation are local operations. They do not
initialize a client or credentials. HTTPX is installed for the network client;
its presence does not require a running gateway.

E18 will implement portable exports and a reader independent of every server.
It may use these pure models and validators, but must not import client/auth,
gateway, database or generated service-runtime modules. E4 provides no portable
bundle reader or export command. These are preview contracts, not a qualified
open-source release or a stable SDK.
