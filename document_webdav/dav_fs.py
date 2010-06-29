# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import pooler

import base64
import sys
import os
import time
from string import joinfields, split, lower

from service import security

import netsvc
import urlparse

from DAV.constants import COLLECTION, OBJECT
from DAV.errors import *
from DAV.iface import *
import urllib

from DAV.davcmd import copyone, copytree, moveone, movetree, delone, deltree
from document.nodes import node_res_dir, node_res_obj
from cache import memoize
from tools import misc
CACHE_SIZE=20000

#hack for urlparse: add webdav in the net protocols
urlparse.uses_netloc.append('webdav')
urlparse.uses_netloc.append('webdavs')

class openerp_dav_handler(dav_interface):
    """
    This class models a OpenERP interface for the DAV server
    """
    PROPS={'DAV:': dav_interface.PROPS['DAV:'],}

    M_NS={ "DAV:" : dav_interface.M_NS['DAV:'],}

    def __init__(self,  parent, verbose=False):        
        self.db_name_list=[]
        self.parent = parent
        self.baseuri = parent.baseuri
        self.verbose = verbose

    def get_propnames(self, uri):
        props = self.PROPS   
        self.parent.log_message('get propnames: %s' % uri)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            if cr: cr.close()
            # TODO: maybe limit props for databases..?
            return props
        node = self.uri2object(cr, uid, pool, uri2)
        if node:
            props.update(node.get_dav_props(cr))
        cr.close()     
        return props

    def _get_dav_lockdiscovery(self, uri):
        raise DAV_NotFound

    def _get_dav_supportedlock(self, uri):
        raise DAV_NotFound

    def match_prop(self, uri, match, ns, propname):        
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            if cr: cr.close()
            raise DAV_NotFound
        node = self.uri2object(cr, uid, pool, uri2)        
        if not node:
            cr.close()
            raise DAV_NotFound
        res = node.match_dav_eprop(cr, match, ns, propname)        
        cr.close()          
        return res  

    def get_prop(self, uri, ns, propname):
        """ return the value of a given property

            uri        -- uri of the object to get the property of
            ns        -- namespace of the property
            pname        -- name of the property
         """            
        if self.M_NS.has_key(ns):
            return dav_interface.get_prop(self, uri, ns, propname)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            if cr: cr.close()
            raise DAV_NotFound
        node = self.uri2object(cr, uid, pool, uri2)
        if not node:
            cr.close()
            raise DAV_NotFound
        res = node.get_dav_eprop(cr, ns, propname)
        cr.close()        
        return res    

    def get_db(self, uri, rest_ret=False, allow_last=False):
        """Parse the uri and get the dbname and the rest.
           Db name should be the first component in the unix-like
           path supplied in uri.
           
           @param rest_ret Instead of the db_name, return (db_name, rest),
                where rest is the remaining path
           @param allow_last If the dbname is the last component in the
                path, allow it to be resolved. The default False value means
                we will not attempt to use the db, unless there is more
                path.
                
           @return db_name or (dbname, rest) depending on rest_ret,
                will return dbname=False when component is not found.
        """
        
        uri2 = self.uri2local(uri)
        if uri2.startswith('/'):
            uri2 = uri2[1:]
        names=uri2.split('/',1)
        db_name=False
        rest = None
        if allow_last:
            ll = 0
        else:
            ll = 1
        if len(names) > ll and names[0]:
            db_name = names[0]
            names = names[1:]

        if rest_ret:
            if len(names):
                rest = names[0]
            return db_name, rest
        return db_name


    def urijoin(self,*ajoin):
        """ Return the base URI of this request, or even join it with the
            ajoin path elements
        """
        return self.baseuri+ '/'.join(ajoin)

    @memoize(4)
    def db_list(self):
        s = netsvc.ExportService.getService('db')
        result = s.exp_list()
        self.db_name_list=[]
        for db_name in result:
            cr = None
            try:
                db = pooler.get_db_only(db_name)
                cr = db.cursor()
                cr.execute("SELECT id FROM ir_module_module WHERE name = 'document' AND state='installed' ")
                res=cr.fetchone()
                if res and len(res):
                    self.db_name_list.append(db_name)
            except Exception, e:
                self.parent.log_error("Exception in db list: %s" % e)
            finally:
                if cr:
                    cr.close()
        return self.db_name_list

    def get_childs(self, uri, filters=None):
        """ return the child objects as self.baseuris for the given URI """        
        self.parent.log_message('get childs: %s' % uri)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri, allow_last=True)
        
        if not dbname:            
            if cr: cr.close()
            res = map(lambda x: self.urijoin(x), self.db_list())            
            return res
        result = []
        node = self.uri2object(cr, uid, pool, uri2[:])
        
        if not node:
            if cr: cr.close()
            raise DAV_NotFound(uri2)
        else:
            fp = node.full_path()
            if fp and len(fp):
                self.parent.log_message('childs: @%s' % fp)
                fp = '/'.join(fp)
            else:
                fp = None
            domain = None
            if filters:
                domain = node.get_domain(cr, filters)
            for d in node.children(cr, domain):
                self.parent.log_message('child: %s' % d.path)                
                if fp:
                    result.append( self.urijoin(dbname,fp,d.path) )
                else:
                    result.append( self.urijoin(dbname,d.path) )
        if cr: cr.close()        
        return result

    def uri2local(self, uri):
        uparts=urlparse.urlparse(uri)
        reluri=uparts[2]
        if reluri and reluri[-1]=="/":
            reluri=reluri[:-1]
        return reluri

    #
    # pos: -1 to get the parent of the uri
    #
    def get_cr(self, uri, allow_last=False):
        """ Split the uri, grab a cursor for that db
        """
        pdb = self.parent.auth_proxy.last_auth
        dbname, uri2 = self.get_db(uri, rest_ret=True, allow_last=allow_last)
        uri2 = (uri2 and uri2.split('/')) or []
        if not dbname:
            return None, None, None, False, uri2
        # if dbname was in our uri, we should have authenticated
        # against that.
        assert pdb == dbname, " %s != %s" %(pdb, dbname)
        res = self.parent.auth_proxy.auth_creds.get(dbname, False)
        if not res:
            self.parent.auth_proxy.checkRequest(self.parent, uri, dbname)
            res = self.parent.auth_proxy.auth_creds[dbname]
        user, passwd, dbn2, uid = res
        db,pool = pooler.get_db_and_pool(dbname)
        cr = db.cursor()
        return cr, uid, pool, dbname, uri2

    def uri2object(self, cr, uid, pool, uri):
        if not uid:
            return None
        return pool.get('document.directory').get_object(cr, uid, uri)

    def get_data(self,uri, rrange=None):
        self.parent.log_message('GET: %s' % uri)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        try:
            if not dbname:
                raise DAV_Error, 409
            node = self.uri2object(cr, uid, pool, uri2)   
            if not node:
                raise DAV_NotFound(uri2)
            try:
                if rrange:
                    self.parent.log_error("Doc get_data cannot use range")
                    raise DAV_Error(409)
                datas = node.get_data(cr)
            except TypeError,e:
                import traceback                
                self.parent.log_error("GET typeError: %s", str(e))
                self.parent.log_message("Exc: %s",traceback.format_exc())
                raise DAV_Forbidden
            except IndexError,e :
                self.parent.log_error("GET IndexError: %s", str(e))
                raise DAV_NotFound(uri2)
            except Exception,e:
                import traceback
                self.parent.log_error("GET exception: %s",str(e))
                self.parent.log_message("Exc: %s", traceback.format_exc())
                raise DAV_Error, 409
            return datas
        finally:
            if cr: cr.close()    

    @memoize(CACHE_SIZE)
    def _get_dav_resourcetype(self,uri):
        """ return type of object """        
        self.parent.log_message('get RT: %s' % uri)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        try:
            if not dbname:
                return COLLECTION
            node = self.uri2object(cr,uid,pool, uri2)
            if not node:
                raise DAV_NotFound(uri2)
            if node.type in ('collection','database'):
                return COLLECTION
            return OBJECT
        finally:
            if cr: cr.close()

    def _get_dav_displayname(self,uri):
        self.parent.log_message('get DN: %s' % uri)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            cr.close()
            return COLLECTION
        node = self.uri2object(cr, uid, pool, uri2)
        if not node:
            cr.close()
            raise DAV_NotFound(uri2)
        cr.close()
        return node.displayname

    @memoize(CACHE_SIZE)
    def _get_dav_getcontentlength(self, uri):
        """ return the content length of an object """        
        self.parent.log_message('get length: %s' % uri)
        result = 0
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)        
        if not dbname:
            if cr: cr.close()
            return str(result)
        node = self.uri2object(cr, uid, pool, uri2)
        if not node:
            cr.close()
            raise DAV_NotFound(uri2)
        result = node.content_length or 0
        cr.close()
        return str(result)

    @memoize(CACHE_SIZE)
    def _get_dav_getetag(self,uri):
        """ return the ETag of an object """
        self.parent.log_message('get etag: %s' % uri)
        result = 0
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            cr.close()
            return '0'
        node = self.uri2object(cr, uid, pool, uri2)
        if not node:
            cr.close()
            raise DAV_NotFound(uri2)
        result = node.get_etag(cr)
        cr.close()
        return str(result)

    @memoize(CACHE_SIZE)
    def get_lastmodified(self, uri):
        """ return the last modified date of the object """
        today = time.time()
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            return today
        try:            
            node = self.uri2object(cr, uid, pool, uri2)
            if not node:
                raise DAV_NotFound(uri2)
            if node.write_date:
                return time.mktime(time.strptime(node.write_date,'%Y-%m-%d %H:%M:%S'))
            else:
                return today
        finally:
            if cr: cr.close()

    @memoize(CACHE_SIZE)
    def get_creationdate(self, uri):
        """ return the last modified date of the object """        
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            raise DAV_Error, 409
        try:            
            node = self.uri2object(cr, uid, pool, uri2)
            if not node:
                raise DAV_NotFound(uri2)            
            if node.create_date:
                result = time.mktime(time.strptime(node.create_date,'%Y-%m-%d %H:%M:%S'))
            else:
                result = time.time()
            return result
        finally:
            if cr: cr.close()

    @memoize(CACHE_SIZE)
    def _get_dav_getcontenttype(self,uri):
        self.parent.log_message('get contenttype: %s' % uri)
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)
        if not dbname:
            return 'httpd/unix-directory'
        try:            
            node = self.uri2object(cr, uid, pool, uri2)
            if not node:
                raise DAV_NotFound(uri2)
            result = str(node.mimetype)
            return result
            #raise DAV_NotFound, 'Could not find %s' % path
        finally:
            if cr: cr.close()    
    
    def mkcol(self,uri):
        """ create a new collection """                  
        self.parent.log_message('MKCOL: %s' % uri)
        uri = self.uri2local(uri)[1:]
        if uri[-1]=='/':uri=uri[:-1]
        parent = '/'.join(uri.split('/')[:-1])        
        parent = self.baseuri + parent
        uri = self.baseuri + uri        
        cr, uid, pool,dbname, uri2 = self.get_cr(uri)
        if not dbname:
            raise DAV_Error, 409
        node = self.uri2object(cr,uid,pool, uri2[:-1])
        if node:
            node.create_child_collection(cr, uri2[-1])  
            cr.commit()      
        cr.close()
        return True

    def put(self, uri, data, content_type=None):
        """ put the object into the filesystem """
        self.parent.log_message('Putting %s (%d), %s'%( misc.ustr(uri), data and len(data) or 0, content_type))
        parent='/'.join(uri.split('/')[:-1])
        cr, uid, pool,dbname, uri2 = self.get_cr(uri)
        if not dbname:
            raise DAV_Forbidden
        try:
            node = self.uri2object(cr, uid, pool, uri2[:])
        except:
            node = False
        
        objname = uri2[-1]
        ext = objname.find('.') >0 and objname.split('.')[1] or False

        if not node:
            dir_node = self.uri2object(cr, uid, pool, uri2[:-1])
            if not dir_node:
                raise DAV_NotFound('Parent folder not found')
            try:
                dir_node.create_child(cr, objname, data)
            except Exception,e:
                import traceback
                self.parent.log_error("Cannot create %s: %s", objname, str(e))
                self.parent.log_message("Exc: %s",traceback.format_exc())
                raise DAV_Forbidden
        else:
            try:
                node.set_data(cr, data)
            except Exception,e:
                import traceback
                self.parent.log_error("Cannot save %s: %s", objname, str(e))
                self.parent.log_message("Exc: %s",traceback.format_exc())
                raise DAV_Forbidden
            
        cr.commit()
        cr.close()
        return 201

    def rmcol(self,uri):
        """ delete a collection """
        cr, uid, pool, dbname, uri2 = self.get_cr(uri)        
        if not dbname:
            raise DAV_Error, 409
        node = self.uri2object(cr, uid, pool, uri2)             
        node.rmcol(cr)

        cr.commit()
        cr.close()
        return 204

    def rm(self,uri):
        cr, uid, pool,dbname, uri2 = self.get_cr(uri)
        if not dbname:        
            cr.close()
            raise DAV_Error, 409
        node = self.uri2object(cr, uid, pool, uri2)
        res = node.rm(cr)
        if not res:
            raise OSError(1, 'Operation not permited.')        
        cr.commit()
        cr.close()
        return 204

    ### DELETE handlers (examples)
    ### (we use the predefined methods in davcmd instead of doing
    ### a rm directly
    ###

    def delone(self, uri):
        """ delete a single resource

        You have to return a result dict of the form
        uri:error_code
        or None if everything's ok

        """
        if uri[-1]=='/':uri=uri[:-1]
        res=delone(self,uri)
        parent='/'.join(uri.split('/')[:-1])
        return res

    def deltree(self, uri):
        """ delete a collection

        You have to return a result dict of the form
        uri:error_code
        or None if everything's ok
        """
        if uri[-1]=='/':uri=uri[:-1]
        res=deltree(self, uri)
        parent='/'.join(uri.split('/')[:-1])
        return res


    ###
    ### MOVE handlers (examples)
    ###

    def moveone(self, src, dst, overwrite):
        """ move one resource with Depth=0

        an alternative implementation would be

        result_code=201
        if overwrite:
            result_code=204
            r=os.system("rm -f '%s'" %dst)
            if r: return 412
        r=os.system("mv '%s' '%s'" %(src,dst))
        if r: return 412
        return result_code

        (untested!). This would not use the davcmd functions
        and thus can only detect errors directly on the root node.
        """
        res=moveone(self, src, dst, overwrite)
        return res

    def movetree(self, src, dst, overwrite):
        """ move a collection with Depth=infinity

        an alternative implementation would be

        result_code=201
        if overwrite:
            result_code=204
            r=os.system("rm -rf '%s'" %dst)
            if r: return 412
        r=os.system("mv '%s' '%s'" %(src,dst))
        if r: return 412
        return result_code

        (untested!). This would not use the davcmd functions
        and thus can only detect errors directly on the root node"""

        res=movetree(self, src, dst, overwrite)
        return res

    ###
    ### COPY handlers
    ###

    def copyone(self, src, dst, overwrite):
        """ copy one resource with Depth=0

        an alternative implementation would be

        result_code=201
        if overwrite:
            result_code=204
            r=os.system("rm -f '%s'" %dst)
            if r: return 412
        r=os.system("cp '%s' '%s'" %(src,dst))
        if r: return 412
        return result_code

        (untested!). This would not use the davcmd functions
        and thus can only detect errors directly on the root node.
        """
        res=copyone(self, src, dst, overwrite)
        return res

    def copytree(self, src, dst, overwrite):
        """ copy a collection with Depth=infinity

        an alternative implementation would be

        result_code=201
        if overwrite:
            result_code=204
            r=os.system("rm -rf '%s'" %dst)
            if r: return 412
        r=os.system("cp -r '%s' '%s'" %(src,dst))
        if r: return 412
        return result_code

        (untested!). This would not use the davcmd functions
        and thus can only detect errors directly on the root node"""
        res=copytree(self, src, dst, overwrite)
        return res

    ###
    ### copy methods.
    ### This methods actually copy something. low-level
    ### They are called by the davcmd utility functions
    ### copytree and copyone (not the above!)
    ### Look in davcmd.py for further details.
    ###

    def copy(self, src, dst):
        src=urllib.unquote(src)
        dst=urllib.unquote(dst)
        ct = self._get_dav_getcontenttype(src)
        data = self.get_data(src)
        self.put(dst, data, ct)
        return 201

    def copycol(self, src, dst):
        """ copy a collection.

        As this is not recursive (the davserver recurses itself)
        we will only create a new directory here. For some more
        advanced systems we might also have to copy properties from
        the source to the destination.
        """
        print " copy a collection."
        return self.mkcol(dst)


    def exists(self, uri):
        """ test if a resource exists """
        result = False
        cr, uid, pool,dbname, uri2 = self.get_cr(uri)
        if not dbname:
            if cr: cr.close()
            return True
        try:
            node = self.uri2object(cr, uid, pool, uri2)
            if node:
                result = True
        except:
            pass
        cr.close()
        return result

    @memoize(CACHE_SIZE)
    def is_collection(self, uri):
        """ test if the given uri is a collection """
        return self._get_dav_resourcetype(uri)==COLLECTION

#eof
