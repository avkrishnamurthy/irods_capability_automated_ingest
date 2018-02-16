import os
from os.path import dirname, getsize, getmtime
from irods.session import iRODSSession
import logging
import sys
import socket

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s:%(name)s:%(levelname)s:%(message)s")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
logger.addHandler(handler)


def call(hdlr_mod, hdlr, func, *args, **options):
    if hasattr(hdlr_mod, hdlr):
        logger.debug("calling " + hdlr + " event handler: args = " + str(args) + ", options = " + str(options))
        getattr(hdlr_mod, hdlr)(func, *args, **options)
    else:
        func(*args, **options)

    
def create_dirs(hdlr_mod, session, target, path, **options):
    if not session.collections.exists(target):
        if target == "/":
            raise Exception("create_dirs: Cannot create root")
        create_dirs(hdlr_mod, session, dirname(target), dirname(path), **options)

        def ccfunc(session, target, path, **options):
            logger.info("creating collection " + target)
            session.collections.create(target)

        call(hdlr_mod, "on_coll_create", ccfunc, session, target, path, **options)

def register_file(hdlr_mod, session, target, path, **options):
    if hasattr(hdlr_mod, "to_resource_hier"):
        options["resc_hier"] = hdlr_mod.to_resource_hier(session, target, path, **options)

    logger.info("registering object " + target + ", options = " + str(options))
    session.data_objects.register(path, target, **options)

def upload_file(hdlr_mod, session, target, path, **options):
    if hasattr(hdlr_mod, "to_resource_hier"):
        options["resc_hier"] = hdlr_mod.to_resource_hier(session, target, path, **options)

    logger.info("uploading object " + target + ", options = " + str(options))
    session.data_objects.put(path, target, **options)

def sync_file(hdlr_mod, session, target, path, **options):
    logger.info("syncing object " + target + ", options = " + str(options))
    upload_file(hdlr_mod, session, target, path, **options)
    
def update_metadata(hdlr_mod, session, target, path, **options):
    size = getsize(path)
    mtime = int(getmtime(path))
    logger.info("updating object: " + target + ", options = " + str(options))

    data_obj_info = {"objPath": target}
    if hasattr(hdlr_mod, "to_resource_hier"):
        data_obj_info["rescHier"] = hdlr_mod.to_resource_hier(session, target, path, **options)

    session.data_objects.modDataObjMeta(data_obj_info, {"dataSize":size, "dataModify":mtime}, **options)

def sync_data_from_file(target, path, hdlr, **options):
    if hdlr is not None:
        hdlr_mod0 = __import__(hdlr)
        hdlr_mod = getattr(hdlr_mod0, "event_handler", None)
    else:
        hdlr_mod = None

    env_file = os.environ.get('IRODS_ENVIRONMENT_FILE')
    if env_file is None:
        env_file = os.path.expanduser('~/.irods/irods_environment.json')

    if hasattr(hdlr_mod, "as_user"):
        client_zone, client_user = hdlr_mod.as_user(target, path, **options)
        sess_ctx = iRODSSession(irods_env_file=env_file, client_user = client_user, client_zone = client_zone)
    else:
        sess_ctx = iRODSSession(irods_env_file=env_file)
        
    def remote_host(session):
        return session.host not in ('localhost', socket.gethostname())

    with sess_ctx as session:    

        if session.data_objects.exists(target):
            create = False
        elif session.collections.exists(target):
            raise Exception("sync: cannot syncing file " + path + " to collection " + target)
        else:
            create = True

        if create:
            create_dirs(hdlr_mod, session, dirname(target), dirname(path), **options)

        if create:
            def cfunc(hdlr_mod, session, target, path, **options):
                if remote_host(session):
                    upload_file(hdlr_mod, session, target, path, **options)
                else:
                    register_file(hdlr_mod, session, target, path, **options)

            call(hdlr_mod, "on_data_obj_create", cfunc, hdlr_mod, session, target, path, **options)
        else:
            def mfunc(hdlr_mod, session, target, path, **options):
                if remote_host(session):
                    sync_file(hdlr_mod, session, target, path, **options)
                else:
                    update_metadata(hdlr_mod, session, target, path, **options)

            call(hdlr_mod, "on_data_obj_modify", mfunc, hdlr_mod, session, target, path, **options)

                
        
