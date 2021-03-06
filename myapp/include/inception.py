import sys, datetime
from django.contrib.auth.models import User
from myapp.include.encrypt import prpcrypt
from myapp.include import function as func
from myapp.models import Db_name,Db_account,Db_instance,Oper_log,Task,Incep_error_log
from myapp.etc import config
from mypro import settings
reload(sys)
sys.setdefaultencoding('utf8')
from django.db import connection, connections

try:
    import MySQLdb
except:
    import pymysql as MySQLdb


def make_sure_mysql_usable():
    # mysql is lazily connected to in django.
    # connection.connection is None means
    # you have not connected to mysql before
    if connection.connection and not connection.is_usable():
        # destroy the default mysql connection
        # after this line, when you use ORM methods
        # django will reconnect to the default mysql
        del connections._connections.default


host = settings.DATABASES['default']['HOST']
port = settings.DATABASES['default']['PORT']
user = settings.DATABASES['default']['USER']
passwd = settings.DATABASES['default']['PASSWORD']
dbname = settings.DATABASES['default']['NAME']
select_limit = int(config.select_limit)
export_limit = int(config.export_limit)
wrong_msg = config.wrong_msg
incp_host = config.incp_host
incp_port = int(config.incp_port)
incp_user = config.incp_user
incp_passwd = config.incp_passwd
public_user = config.public_user
pttool_switch = config.pt_tool
pttool_path = config.pt_tool_path
incept_backup_host = config.incept_backup_host
incept_backup_port = config.incept_backup_port
incept_backup_user = config.incept_backup_user
incept_backup_passwd = config.incept_backup_passwd


#0 for check and 1 for execute
def incep_exec(sqltext, myuser, mypasswd, myhost, myport, mydbname, flag=0):
    pc = prpcrypt()
    if int(flag) == 0:
        flagcheck='--enable-check'
    elif int(flag) == 1:
        flagcheck='--enable-execute; --enable-remote-backup'
    elif int(flag) == 2:
        flagcheck = '--enable-split'
    elif int(flag) == 3:
        flagcheck = '--enable-execute; --disable-remote-backup'
    myuser = myuser.encode('utf8')
    mypasswd = pc.decrypt(mypasswd.encode('utf8'))
    myhost = myhost.encode('utf8')
    myport = int(myport)
    mydbname = mydbname.encode('utf8')
    sql1 = "/*--user=%s;--password=%s;--host=%s;%s;--port=%d;*/\
            inception_magic_start;\
            use %s;" % (myuser, mypasswd, myhost, flagcheck, myport, mydbname)
    sql2 = 'inception_magic_commit;'
    sql = sql1 + sqltext + sql2
    try:
        conn = MySQLdb.connect(host=incp_host, user=incp_user, passwd=incp_passwd, db='', port=incp_port,
                             use_unicode=True, charset="utf8")
        cur = conn.cursor()
        ret = cur.execute(sql)
        result = cur.fetchall()
        #num_fields = len(cur.description)
        field_names = [i[0] for i in cur.description]
        cur.close()
        conn.close()
    except MySQLdb.Error as e:
        return([str(e)], ''), ['error']
    return result, field_names
    #return result[1][4].split("\n")


#flag=0 for check and 1 for execute
def inception_check(hosttag, sql, flag=0):
    make_sure_mysql_usable()
    a = Db_name.objects.get(dbtag=hosttag)
    #a = Db_name.objects.get(dbtag=hosttag)
    tar_dbname = a.dbname
    if not cmp(sql, wrong_msg):
        results, col = func.mysql_query(wrong_msg, user, passwd, host, int(port), dbname)
        return results, col, tar_dbname
    try:
        if a.instance.all().filter(role='write')[0]:
            tar_host = a.instance.all().filter(role='write')[0].ip
            tar_port = a.instance.all().filter(role='write')[0].port
    except:
        try:
            tar_host = a.instance.all().filter(role='all')[0].ip
            tar_port = a.instance.all().filter(role='all')[0].port
        except Exception as e:
            wrongmsg = "select \"" + str(e).replace('"',"\"")+"\""
            results,col = func.mysql_query(wrongmsg,user,passwd,host,int(port),dbname)
            return results, col, tar_dbname
    for i in a.db_account_set.all():
        if i.role == 'admin':
            tar_username = i.user
            tar_passwd = i.passwd
            break
    #print tar_port+tar_passwd+tar_username+tar_host
    try:
        results, col = incep_exec(sql, tar_username, tar_passwd, tar_host, tar_port, tar_dbname, flag)
        return results, col, tar_dbname
    except:
        wrongmsg = "select \"no admin account being setted\""
        results, col = func.mysql_query(wrongmsg, user, passwd, host, int(port), dbname)
        return results, col, tar_dbname


def task_check(idnum,request):
    task = Task.objects.get(id=idnum)
    if task.status != 'executed' and task.status != 'running' and task.status != 'executed failed':
        hosttag = task.dbtag
        sql = task.sqltext
        results, col, dbname = inception_check(hosttag, sql, 2)
        if len(results) > 1:
            status = 'check not passed'
        else:
            results, col, dbname = inception_check(hosttag, sql)
            status = 'check passed'
            str = ''
            for row in results:
                if int(row[2]) != 0:
                    status='check not passed'
                #record all sqlsha and sqltext of the task into task.sqlsha
                if row[10] != '':
                    str = str+row[5]+row[10]+'^^'
            task.sqlsha = str
        task.status = status
        task.operator = request.user.username
        task.update_time = datetime.datetime.now()
        task.save()
        return results, col, dbname
    else:
        return [], [], ''


#'executed','executed failed','check not passed','check passed','running','appointed','NULL'
def check_task_status(id):
    try:
        task = Task.objects.get(id=id)
    except:
        return False, "ID NOT EXISTS , PLEASE CHECK !"
    status = task.status
    if status == 'NULL' or status == 'executed failed' or status == 'check not passed' or status == 'check passed':
        return True, "CAN BE UPDATED"
    else:
        return False, "TASK IN THIS STATUS CAN'T BE UPDATED,PLEASE CHECK!"


def get_task_forupdate(id):
    task_data = Task.objects.get(id=id)
    return task_data


def update_task(id, sqltext, specify, status, needbackup, username):
    task_data = Task.objects.get(id=id)
    old_sqltext = task_data.sqltext
    old_status = task_data.status
    task_data.sqltext = sqltext
    task_data.specification = specify
    task_data.backup_status = needbackup
    list = ['executed', 'executed failed', 'check not passed', 'check passed', 'running', 'appointed', 'NULL']
    if status in list:
        task_data.status=status
        task_data.operator=username
    task_data.update_time = datetime.datetime.now()
    #if old_sqltext != sqltext ,then update the status to NULL
    if cmp(old_sqltext, sqltext) and (not cmp(status, old_status)):
        if needbackup == 2:
            task_data.backup_status = 1
        task_data.status = 'NULL'
    task_data.save()


#"can_admin_task" users can see all tasks ,others can only see their own tasks
def get_task_list(dbtag, request, end):
    username = request.user.username
    if request.user.has_perm('myapp.can_admin_task'):
        if dbtag == 'all':
            task_list = Task.objects.filter(create_time__lte=end).order_by("-create_time")[0:50]
        else:
            task_list = Task.objects.filter(dbtag=dbtag).filter(create_time__lte=end).order_by("-create_time")[0:50]
    else:
        if dbtag == 'all':
            task_list = Task.objects.filter(user=username).filter(create_time__lte=end).order_by("-create_time")[0:50]
        else:
            task_list = Task.objects.filter(dbtag=dbtag).filter(
                create_time__lte=end).filter(user=username).order_by("-create_time")[0:50]
    return task_list


def delete_task(idnum):
    task = Task.objects.get(id=idnum)
    if task.status != 'executed' and task.status != 'running':
        task.delete()


#add task to tasktable
def record_task(request, sqltext, dbtag, specify, ifbackup):
    username = request.user.username
    #lastlogin = user.last_login+datetime.timedelta(hours=8)
    #create_time = datetime.datetime.now()+datetime.timedelta(hours=8)
    create_time = datetime.datetime.now()
    update_time = datetime.datetime.now()
    status = 'NULL'
    mytask = Task(user=username, sqltext=sqltext, create_time=create_time, update_time=update_time, dbtag=dbtag,
                  status=status, specification=specify, backup_status=ifbackup)
    mytask.save()
    return 1


def log_incep_op(sqltext, dbtag, request, mycreatetime):
    user = User.objects.get(username=request.user.username)
    lastlogin = user.last_login
    create_time = mycreatetime
    username = user.username
    sqltype = 'incept'
    ipaddr = func.get_client_ip(request)
    log = Oper_log(user=username, sqltext=sqltext, sqltype=sqltype, login_time=lastlogin, create_time=create_time,
                   dbname='', dbtag=dbtag, ipaddr=ipaddr)
    log.save()
    return 1


def get_db_info(hosttag):
    a = Db_name.objects.get(dbtag=hosttag)
    tar_dbname = a.dbname
    try:
        if a.instance.all().filter(role='write')[0]:
            tar_host = a.instance.all().filter(role='write')[0].ip
            tar_port = a.instance.all().filter(role='write')[0].port
    except:
        try:
            tar_host = a.instance.all().filter(role='all')[0].ip
            tar_port = a.instance.all().filter(role='all')[0].port
        except:
            pass
    for i in a.db_account_set.all():
        if i.role == 'admin':
            tar_username = i.user
            tar_passwd = i.passwd
            break
    return tar_username, tar_passwd, tar_host,  tar_port,tar_dbname


def rollback_sqllist(idnum):
    task = Task.objects.get(id=idnum)
    sqllist = []
    if task.backup_status == 2:
        data = Incep_error_log.objects.filter(
            create_time=task.create_time).filter(finish_time=task.update_time).order_by("-myid")
        for i in data:
            backupDb = i.backup_db
            if backupDb == 'None':
                continue
            opid_time = i.sequence.replace("'","")
            sqllist = sqllist + get_single_rollback(backupDb,opid_time)
    return sqllist


def rollback_sql(seq):
    a = Incep_error_log.objects.filter(sequence=seq)[:1]
    backupDb = a[0].backup_db
    opid_time = seq.replace("'","")
    sqllist = []
    if backupDb != 'None' and len(a[0].stagestatus) == 40:
        sqllist = get_single_rollback(backupDb,opid_time)
    return sqllist


def get_single_rollback(backupDb,opid_time):
    sqllist = []
    tbNamesql = "select tablename from %s.$_$Inception_backup_information$_$ where opid_time='%s';" % (backupDb, opid_time)
    results, col = func.mysql_query(tbNamesql, incept_backup_user, incept_backup_passwd, incept_backup_host,
                                    int(incept_backup_port), backupDb)
    tbName = results[0][0]
    backsql = "select rollback_statement from %s.%s where opid_time='%s' order by id desc" % (backupDb, tbName, opid_time)
    results,col = func.mysql_query(backsql, incept_backup_user, incept_backup_passwd, incept_backup_host,
                                   int(incept_backup_port), backupDb)
    for row in results :
        sqllist.append(row[0])
    return sqllist


def task_running_status(idnum):
    task = Task.objects.get(id=idnum)
    if task.status == 'executed failed'or task.status == 'executed':
        data = Incep_error_log.objects.filter(
            create_time=task.create_time).filter(finish_time=task.update_time).order_by("-myid")
        col = [f.name for f in Incep_error_log._meta.get_fields()]
        #delete first element "ID"
        del col[0]
        return data, col
    elif task.status == 'running':
        text = task.sqlsha
        if text == '':
            try:
                tar_username, tar_passwd, tar_host,  tar_port,tar_dbname = get_db_info(task.dbtag)
                sql = "select * from information_schema.processlist where Db='" + \
                      tar_dbname + "'" + " and USER='" + tar_username + "' order by TIME desc"
                return func.mysql_query(sql, tar_username, tar_passwd, tar_host, int(tar_port), 'information_schema')
            except:
                return(['get info wrong'],''), ['info']
        else:
            for i in text.split('^^'):
                x = i.split('*')
                if len(x) >= 2:
                    sqlsha = '*' + x[1]
                    datalist, collist, mynum = incep_getstatus(sqlsha)
                    #add sqltext to the end of the tuple
                    if mynum > 0:
                        for d in datalist:
                            data = d+(x[0],)
                        collist.append('SQLTEXT')
                        cols = collist
                        data = (data,)
                        break
            if not vars().has_key('data'):
                data = (['wait in running queue'], '')
                cols = ['info']
            return data, cols
    elif task.status == 'check passed':
        if task.sqlsha == '':
            data = (['not running and not use pt-online-schema-change'], '')
        else :
            data = (['not running and will use pt-online-schema-change'], '')
        cols = ['info']
        return data, cols
    else :
        return (['not running'],''),['info']


def incep_getstatus(sqlsha):
    text = sqlsha
    sql = 'inception get osc_percent \'%s\'' % text
    try:
        conn = MySQLdb.connect(host=incp_host, user=incp_user, passwd=incp_passwd, db='', port=incp_port,
                               use_unicode=True, charset="utf8")
        cur = conn.cursor()
        ret = cur.execute(sql)
        result = cur.fetchall()
        my_field_names = [i[0] for i in cur.description]
        cur.close()
        conn.close()
        return result, my_field_names, ret
    except Exception as e:
        return([str(e)], ''), ['error'], 0


def set_schetime(idnum, schetime):
    task = Task.objects.get(id=idnum)
    #can only appointed task in 'check passed' status
    if task.status == 'check passed':
        task.status = 'appointed'
        task.sche_time = schetime
        task.save()


def incep_stop(sqlsha, request):
    text = sqlsha
    if text[0] == '*':
        sql = 'inception stop alter \'%s\'' %(text)
    #use inception to kill sqlsha
        try:
            conn = MySQLdb.connect(host=incp_host, user=incp_user, passwd=incp_passwd, db='', port=incp_port,
                                   use_unicode=True, charset="utf8")
            cur = conn.cursor()
            ret = cur.execute(sql)
            # result=cur.fetchall()
            field_names = ['success']
            cur.close()
            conn.close()
            result = ([sqlsha+' is stopped'],)
            return result, field_names
        except Exception as e:
            return([str(e)],''), ['error']
    #kill id
    else:
        try:
            id = request.session['recent_taskid']
            task = Task.objects.get(id=id)
            tar_username, tar_passwd, tar_host, tar_port, tar_dbname = get_db_info(task.dbtag)
            sql = "kill " + sqlsha
            conn = MySQLdb.connect(host=tar_host, user=tar_username, passwd=tar_passwd, port=int(tar_port),
                                   connect_timeout=5, charset='utf8')
            conn.select_db(tar_dbname)
            curs = conn.cursor()
            result = curs.execute(sql)
            conn.commit()
            curs.close()
            conn.close()
            return ([sqlsha + ' killed '], ''), ['success']
        except Exception as e:
            return ([str(e)], ''), ['error']


def main():
    x, y, z = incep_exec("insert into t2 values(2);", 'test', 'test', '10.1.70.220', 3306, 'test')


if __name__ == '__main__':
    main()