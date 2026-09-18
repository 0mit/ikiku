# Part of place_responder. Licensed under AGPL-3.0.
#
# The image is the binary and nothing else: no shell, no package manager, nothing to patch.
# Built on a machine with Go (make image), shipped with `docker save | ssh ... docker load`,
# because the production host cannot be relied on to reach a registry.
FROM scratch
COPY place_responder /place_responder
USER 65534:65534
EXPOSE 8070 8071
ENTRYPOINT ["/place_responder"]
