#!/usr/bin/python

import os
import select
import socket

from OpenSSL import SSL

import libmu.defs
import libmu.machine_state

###
#  server mainloop
###
def server_main_loop(states, handle_server_sock, num_parts, basename, chainfile=None, keyfile=None):
    # bro, you listening to this?
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(('0.0.0.0', 13579))
    lsock.listen(num_parts + 10) # lol like the kernel listens to me

    sslctx = SSL.Context(SSL.TLSv1_2_METHOD)
    sslctx.set_options(SSL.OP_NO_COMPRESSION)
    sslctx.set_cipher_list(libmu.defs.Defs.cipher_list)
    sslctx.set_verify(SSL.VERIFY_NONE, lambda *_: True)

    # set up server key
    if chainfile is None or keyfile is None:
        sslctx.use_certificate_chain_file(os.environ.get('CERTIFICATE_CHAIN', 'server_chain.pem'))
        sslctx.use_privatekey_file(os.environ.get('PRIVATE_KEY', 'server_key.pem'))
    else:
        sslctx.use_certificate_chain_file(chainfile)
        sslctx.use_privatekey_file(keyfile)
    sslctx.check_privatekey()

    # set up server SSL connection
    lsock = SSL.Connection(sslctx, lsock)
    lsock.set_accept_state()
    lsock.setblocking(False)

    def rwsplit(sts):
        rs = []
        ws = []
        for st in sts:
            if st.sock is None:
                continue

            if not isinstance(st, libmu.machine_state.TerminalState):
                rs.append(st)

            if st.ssl_write or st.want_write:
                ws.append(st)

        return (rs, ws)

    while True:
        (readSocks, writeSocks) = rwsplit(states)

        if len(readSocks) == 0 and len(writeSocks) == 0 and lsock is None:
            break

        if lsock is not None:
            readSocks += [lsock]

        (rfds, wfds, _) = select.select(readSocks, writeSocks, [], libmu.defs.Defs.timeout)

        if len(rfds) == 0 and len(wfds) == 0:
            print "SERVER TIMEOUT"
            break

        for r in rfds:
            if r is lsock:
                lsock = handle_server_sock(lsock, states, num_parts, basename)

            else:
                rnext = r.do_read()
                states[rnext.actorNum] = rnext

        for w in wfds:
            # reading might have caused this state to get updated,
            # so we index into states to be sure we have the freshest version
            actorNum = w.actorNum
            wnext = states[actorNum].do_write()
            states[actorNum] = wnext

        for r in readSocks:
            if not isinstance(r, libmu.machine_state.MachineState):
                continue

            rnum = r.actorNum
            rnext = states[rnum]
            if rnext.want_handle:
                rnext = rnext.do_handle()

            states[rnum] = rnext

    error = False
    for state in states:
        state.close()
        print str(state.get_timestamps())
        if isinstance(state, libmu.machine_state.ErrorState):
            error = True

    if error:
        raise Exception("ERROR: worker terminated abnormally.")
