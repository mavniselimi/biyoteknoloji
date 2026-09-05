"""Translation between the transport contract and the application layer.

Every adapter here is a plain function over plain data: a mapping in, a
mapping or a domain object out. None of them imports a web framework, none
constructs a response object, and none decides anything scientific.

That is the point of the package existing separately from
:mod:`apps.api.routers`. The routers are the part that cannot run in this
environment that had no FastAPI - and the translation is the
part where a mistake would be silent: a dropped reason code, a coverage status
serialised without its attention, an evidence record answered from the
currently active release rather than the pinned one. Keeping the translation
framework-free means all of it is executable and tested here, and the routers
are left holding nothing but wiring.

The direction is strictly one way at a time. ``request`` reads a caller's
document into canonical application types and never looks at a result;
everything else reads a stored or calculated result into a response document
and never looks at a request.
"""
