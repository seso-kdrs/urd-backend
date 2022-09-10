import re
from datetime import date, datetime

class Expression:
    def __init__(self, platform):
        self.platform = platform

    def concat(self, items):
        # Concat expressions and treat null as ''
        if (self.platform == 'mysql'):
            return "concat_ws('', " + ','.join(items) + ")"
        else:
            return ' || '.join(items)

    def concat_ws(self, sep, items):
        if (self.platform == 'mysql'):
            return "concat_ws('" + sep + "'," + ",".join(items) + ")"
        else:
            sep = " || '" + sep + "' || "
            return sep.join(items)

    def autoincrement(self):
        if (self.platform == 'mysql'):
            return "AUTO_INCREMENT"
        elif (self.platform == 'oracle'):
            return "GENERATED BY DEFAULT ON NULL AS IDENTITY"
        elif (self.platform == 'postgres'):
            return "SERIAL"
        elif (self.platform == 'sqlite3'):
            return "AUTOINCREMENT"

    def to_native_type(self, type_, size):
        if self.platform == "mysql":
            if type_ == "string":
                return "varchar(" + str(size) + ")" if size else "longtext"
            elif type_ == "integer":
                return "int(" + str(size) + ")"
            elif type_ == "decimal":
                return "decimal(" + size + ") "
            elif type_ == "float":
                return "float(" + str(size) + ")"
            elif type_ == "date":
                return "date"
            elif type_ == "boolean":
                return "tinyint(1)"
            elif type_ == "binary":
                return "blob"
            else:
                raise ValueError(f"Type {type_} not supported yet")
        elif self.platform == "sqlite3":
            if type_ in ["string"]:
                return "varchar(" + str(size) + ")" if size else "text"
            elif type_ == "date":
                return "date"
            elif type_ in ["integer", "boolean"]:
                return "integer"
            elif type_ == "decimal":
                return "decimal"
            elif type_ == "float":
                return "real"
            elif type_ == "binary":
                return "blob"
            elif type_ == "json":
                return "json"
            else:
                raise ValueError(f"Type {type_} not supported yet")
        elif self.platform == 'postgres':
            if type_ == "string" and size:
                return "varchar(" + str(size) + ")"
            elif type_ == "string":
                return "text"
            elif (type_ == "integer" and size > 11):
                return "bigint"
            elif type_ == "integer":
                return "integer"
            elif type_ == "decimal":
                return "decimal(" + size + ")"
            elif type_ == "float":
                return "float(" + str(size) + ")"
            elif type_ == "date":
                return "date"
            elif type_ == "boolean":
                return "boolean"
            elif type_ == "binary":
                return "bytea"
            elif type_ == "json":
                return "json"
        elif self.platform == 'oracle':
            if (type_ == "string" and size > 4000):
                return "clob"
            elif type_ == "string":
                return "varchar(" + str(size) + ")"
            elif (type_ == "integer" and size > 11):
                return "number(" + str(size) + ", 0)"
            elif type_ == "integer":
                return "integer"
            elif type_ == "float":
                return "float(" + str(size) + ")"
            elif type_ == "date":
                return "date"
            elif type_ == "boolean":
                return "number(1)"
            elif type_ == "binary":
                return "blob"
        else:
            raise ValueError(f"Type conversion for {self.platform} not implemented")

    def to_urd_type(self, type_):
        type_ = type_.lower()
        if self.platform == 'mysql':
            if re.search("char|text", type_):
                return "string"
            elif re.search("int", type_):
                return "integer"
            elif re.search("double|decimal", type_):
                return "decimal"
            elif re.search("float", type_):
                return "float"
            elif re.search("date|time", type_):
                return "date"
            elif type_ == "blob":
                return "binary"
            else:
                raise ValueError(f"Type {type_} not supported yet")
        elif self.platform == "oracle":
            if type_ in ["char", "varchar2", "nvarchar2", "clob", "nclob"]:
                return "string"
            elif type_ == "number":
                return "integer"
            elif type_ in ["decimal"]:
                return "decimal"
            elif type_ in ["date", "timestamp", "timestamp(6)"]:
                return "date"
            elif type_ in ["float"]:
                return "float"
            elif type_ in ["blob"]:
                return "binary"
            else:
                raise ValueError(f"Type {type_} not supported yet")
        else:
            if type_ in ["varchar", "text", "char", "bpchar", "clob"]:
                return "string"
            elif type_ in ["integer", "int", "int4", "int8"]:
                return "integer"
            elif type_ in ["numeric", "decimal"]:
                return "decimal"
            elif type_ in ["float", "float8"]:
                return "float"
            elif type_ == "blob":
                return "binary"
            elif type_ in ["date", "timestamp"]:
                return "date"
            elif type_ in ["bool", "boolean"]:
                return "boolean"
            elif type_ in ["json", "jsonb"]:
                return "json"
            else:
                raise ValueError(f"Type {type_} not supported yet")
    
    def replace_vars(self, sql):
        # todo: Get user from logged in user
        sql = sql.replace("$user_name", "Admin")

        if "current_date" in sql.lower():
            sql = date.today().strftime("%Y-%m-%d")
        elif "current_timestamp" in sql.lower():
            sql = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return sql
        # todo:t Må ha autentisering på plass før denne kan lages

    def databases(self):
        if self.platform == 'postgres':
            return """
            select datname from pg_database
            where datistemplate is false and datname != 'postgres'
            """
        elif self.platform == 'oracle':
            return """
            SELECT DISTINCT OWNER
              FROM ALL_OBJECTS
             WHERE OBJECT_TYPE = 'TABLE'
            order by owner;
            """
    def schemata(self):
        if self.platform == 'postgres':
            return """
            select schema_name
            from information_schema.schemata
            where schema_name != 'information_schema'
              and schema_name not like 'pg_%';
            """

    def indexes(self):
        if self.platform == 'oracle':
            return """
            select i.index_name, case uniqueness when 'NONUNIQUE' then 1 else 0 end as non_unique,
                   lower(column_name) as column_name, column_position, i.table_name
            from all_indexes i
            join all_ind_columns col on col.index_name = i.index_name
            where i.table_owner = ?
            order by column_position
            """
    def pkeys(self):
        if self.platform == 'oracle':
            return """
            SELECT cols.table_name, cols.column_name, cols.position as key_seq, cons.status, cons.owner
            FROM all_constraints cons, all_cons_columns cols
            WHERE cons.constraint_type = 'P'
            AND cons.constraint_name = cols.constraint_name
            AND cons.owner = cols.owner
            AND cons.owner = ?
            AND cols.table_name = nvl(?, cols.table_name)
            ORDER BY cols.table_name, cols.position;
            """

    def pkey(self, table_name=None):
        if self.platform == 'sqlite3':
            return f"""
            SELECT name as column_name
            FROM pragma_table_info('{table_name}')
            WHERE pk != 0 order by pk
            """

    def fkeys(self):
        if self.platform == 'oracle':
            return """
            SELECT a.column_name as fkcolumn_name, a.position,
                   a.constraint_name as fk_name, a.table_name as fktable_name,
                    c.owner, c.delete_rule,
                    -- referenced pk
                    c.r_owner as pktable_schema, c_pk.table_name as pktable_name,
                    c_pk.constraint_name r_pk,
                    ra.column_name pkcolumn_name
            FROM all_cons_columns a
                JOIN all_constraints c
                ON a.owner = c.owner
                AND a.constraint_name = c.constraint_name
                JOIN all_constraints c_pk
                ON c.r_owner = c_pk.owner
                AND c.r_constraint_name = c_pk.constraint_name
                JOIN all_cons_columns ra
                ON ra.owner = c.owner
                AND ra.constraint_name = c_pk.constraint_name
                AND ra.position = a.position
            WHERE c.constraint_type = 'R'
            AND   a.owner = ?
            ORDER BY a.position
            """
        elif self.platform == 'postgres':
            return """
            select
                con.relname as fktable_name,
                att2.attname as fkcolumn_name,
                ns.nspname as pktable_schema,
                cl.relname as pktable_name,
                att.attname as pkcolumn_name,
                conname as fk_name,
                CASE con.confdeltype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                    ELSE 'UNKNOWN'
                END AS delete_rule,
                CASE con.confupdtype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                    ELSE 'UNKNOWN'
                END AS update_rule
            from
            (select
                    unnest(con1.conkey) as "parent",
                    unnest(con1.confkey) as "child",
                    cl.relname,
                    con1.confrelid,
                    con1.conrelid,
                    con1.conname,
                    con1.confdeltype,
                    con1.confupdtype
                from
                    pg_class cl
                    join pg_namespace ns on cl.relnamespace = ns.oid
                    join pg_constraint con1 on con1.conrelid = cl.oid
                where
                    con1.contype = 'f'
                    and ns.nspname = ?

            ) con
            join pg_attribute att on
                att.attrelid = con.confrelid and att.attnum = con.child
            join pg_class cl on
                cl.oid = con.confrelid
            join pg_attribute att2 on
                att2.attrelid = con.conrelid and att2.attnum = con.parent
            join pg_namespace ns on
                ns.oid=cl.relnamespace

            """

    def columns(self):
        if self.platform == 'oracle':
            return """
            select lower(table_name) as table_name, lower(column_name) as column_name,
                   data_type as type_name, data_length as column_size,
                   case nullable when 'Y' then 1 else 0 end as nullable
            from all_tab_columns
            where owner = ? and table_name = nvl(?, table_name)
            """
        else:
            return None

    def privilege(self):
        if self.platform == 'postgres':
            return """
            select pg_catalog.has_schema_privilege(current_user, nspname, 'CREATE') "create"
            from pg_catalog.pg_namespace
            where nspname = ?
            """
        else:
            return None

    def user_tables(self):
        if self.platform == 'sqlite3':
            return """
            SELECT name as table_name
            FROM   sqlite_master
            WHERE  type IN ('table', 'view');
            """
        elif self.platform == 'oracle':
            return """
            SELECT object_name as table_name
            FROM   all_objects
            WHERE  object_type in ('TABLE', 'VIEW')
                   AND owner = ?;
            """
        else:
            return """
            SELECT table_name
            FROM   information_schema.tables
            WHERE  table_schema = ?;
            """


    def table_privileges(self):
        if self.platform == 'postgres':
            return """
            select privilege_type
            from information_schema.table_privileges
            where grantee = ?
            and table_name = ?;
            """
        else:
            return None
