"""Module for handling tables"""
import time
import datetime
import pypandoc
from addict import Dict
from record import Record
from column import Column
from field import Field
from expression import Expression
from grid import Grid
from sqlglot import parse_one, exp


def measure_time(func):
    def wrapper(*arg):
        t = time.time()
        res = func(*arg)
        if (time.time()-t) > 1:
            print("Time in", func.__name__,  str(time.time()-t), "seconds")
        return res

    return wrapper


class Table:
    """Contains methods for getting metadata for table"""

    def __init__(self, db, tbl_name):
        self.db = db
        self.name = tbl_name
        self.label = db.get_label(tbl_name)
        self.view = tbl_name
        if tbl_name + '_view' in db.user_tables:
            self.view = tbl_name + '_view'
        self.grid_view = self.view
        if tbl_name + '_grid' in db.user_tables:
            self.grid_view = tbl_name + '_grid'
        if hasattr(db, 'tables'):
            for key, val in db.tables[tbl_name].items():
                setattr(self, key, val)

    def get_type(self, main_type=None):
        """Return type of table"""
        if not hasattr(self, 'type'):
            self.init_type(main_type)

        return self.type

    def init_type(self, main_type=None):
        """Find type. One of 'table', 'list', 'xref', 'view' """
        if (self.db.attrs.get("cache", None) and not self.db.config):
            self.type = self.db.attrs.cache.tables[self.name].type
            return self.type

        if not main_type:
            tbl_names = self.db.refl.get_table_names(self.db.schema)
            main_type = 'table' if self.name in tbl_names else 'view'

        pkey = self.get_pkey()
        # Data type of primary key column
        type_ = None

        # Find data type for first pkey column
        if pkey and len(pkey.columns) and pkey.columns != ['rowid']:
            colname = pkey.columns[0]
            cols = self.db.refl.get_columns(self.name, self.db.schema)
            for col in cols:
                if col['name'] == colname:
                    pkey_col = col
                    break
            type_ = pkey_col['type'].python_type.__name__

        tbl_type = main_type

        if (self.name[-5:] == "_list" or self.name[-6:] == "_liste"):
            tbl_type = "list"
        elif self.name[-5:] in ("_xref", "_link"):
            tbl_type = "xref"
        elif self.name[-4:] == "_ext":
            tbl_type = "ext"
        elif type_ == 'str':
            tbl_type = "list"

        self.type = tbl_type

        return tbl_type

    def user_privileges(self):
        """Return privileges of database user"""
        privileges = Dict({
            'select': 1,
            'insert': 1,
            'update': 1,
            'delete': 1
        })
        sql = self.db.expr.table_privileges()
        if sql:
            params = {'user': self.db.user, 'table': self.name}
            rows = self.db.query(sql, params).fetchall()
            for row in rows:
                if row.privilege_type == 'SELECT':
                    privileges.select = 1
                elif row.privilege_type == 'INSERT':
                    privileges.insert = 1
                elif row.privilege_type == 'UPDATE':
                    privileges['update'] = 1
                elif row.privilege_type == 'DELETE':
                    privileges.delete = 1

        return privileges

    @measure_time
    def count_rows(self):
        sql = f'select count(*) from "{self.name}"'
        return self.db.query(sql).first()[0]

    def is_hidden(self):
        """Decide if this is a hidden table"""
        if (
            self.name[0:1] == "_" or
            self.name[0:5] == "meta_"
        ):
            hidden = True
        else:
            hidden = False

        return hidden

    def get_indexes(self):
        """Return all table indexes"""
        if not hasattr(self, 'indexes'):
            self.init_indexes()

        return self.indexes

    def get_fkeys(self):
        """Return all foreign keys of table"""
        if not hasattr(self, 'fkeys'):
            self.init_fkeys()

        return self.fkeys

    def get_fkey(self, name):
        """Return single foreign key based on key name or last column"""
        if not hasattr(self, 'fkeys'):
            self.init_fkeys()

        if name in self.fkeys:
            return self.fkeys[name]
        else:
            col_fkey = None
            for fkey in self.fkeys.values():
                if (fkey.constrained_columns[-1] == name):
                    if (
                        not col_fkey or
                        # If more than one fkey meets the requirement,
                        # choose the one with fewest columns
                        len(fkey.constrained_columns) <
                        len(col_fkey.constrained_columns)
                    ):
                        col_fkey = fkey

            return col_fkey

    def get_fields(self):
        """Return all fields of table"""
        if not hasattr(self, 'fields'):
            self.init_fields()

        return self.fields

    @measure_time
    def get_pkey(self):
        """Return primary key of table"""
        if hasattr(self, 'pkey'):
            return self.pkey
        if (self.db.attrs.get("cache", None) and not self.db.config):
            self.pkey = self.db.attrs.cache.tables[self.name].pkey
            return self.pkey

        pkey = self.db.get_pkey(self.name)

        if (not pkey.columns and self.db.engine.name == 'sqlite'):
            pkey.columns = ['rowid']

        if (not pkey.columns):
            attrs = self.db.html_attrs
            selector = f'table[data-name="{self.name}"]'
            if attrs[selector]['data-pkey']:
                pkey.name = self.name + '_pkey'
                pkey.columns = attrs[selector]['data-pkey']

        self.pkey = pkey
        return pkey

    def get_parent_fk(self):
        """Return foreign key defining hierarchy"""
        # Find relation to child records
        relations = self.get_relations()
        rel = [rel for rel in relations.values() if rel.table == self.name][0]
        fkey = self.get_fkey(rel.name)

        return fkey

    def get_join(self):
        """Return all joins to table as single string"""
        if hasattr(self, 'join'):
            return self.join
        joins = []
        fkeys = self.get_fkeys()
        aliases = []

        for key, fkey in fkeys.items():
            if fkey.referred_table not in self.db.user_tables:
                continue

            alias = fkey.constrained_columns[-1]

            # In seldom cases there might be two foreign keys ending
            # in same column
            if alias in aliases:
                alias = alias + '2'

            aliases.append(alias)

            # Get the ON statement in the join
            ons = [f'"{alias}"."{fkey.referred_columns[idx]}" = '
                   f'"{self.view}"."{col}"'
                   for idx, col in enumerate(fkey.constrained_columns)]
            on_list = ' AND '.join(ons)

            joins.append(f'left join {self.db.schema}."{fkey.referred_table}" '
                         f'"{alias}" on {on_list}')

        self.join = "\n".join(joins)

        return self.join

    def get_relation(self, alias):
        """Return single relation"""
        if not hasattr(self, 'relations'):
            self.init_relations()

        return self.relations[alias]

    def get_relations(self):
        """Return all 'has many' relations of table"""
        if not hasattr(self, 'relations'):
            self.init_relations()

        return self.relations

    def get_rel_tbl_names(self):
        tbl_names = []
        for rel in self.relations.values():
            tbl_names.append(rel.table)

        return tbl_names

    def get_csv(self, columns):
        selects = {}
        for colname in columns:
            selects[colname] = self.name + '.' + colname

        grid = Grid(self)
        records = grid.get_values(selects)

        content = ';'.join(columns) + '\n'

        for rec in records:
            values = []
            for col, val in rec.items():
                if type(val) == str:
                    val = val.replace('"', '""')
                    val = "'" + val + "'"
                elif val is None:
                    val = ''
                else:
                    val = str(val)
                values.append(val)
            content += ';'.join(values) + '\n'

        return content

    def save(self, records: list):
        """Save new and updated records in table"""
        from database import Database
        result = Dict()
        for rec in records:
            rec = Dict(rec)
            record = Record(self.db, self, rec.prim_key)
            if rec.method == 'delete':
                record.delete()
            elif rec.method == 'post':
                pkey = record.insert(rec['values'])

                # Must get autoinc-value for selected record to get
                # correct offset when reloading table after saving
                if 'selected' in rec:
                    result.selected = pkey

            elif rec.method == "put":
                if rec['values']:
                    record.update(rec['values'])

            # Iterates over all the relations to the record
            for key, rel in rec.relations.items():

                if rel.base_name == self.db.name:
                    rel_db = self.db
                else:
                    rel_db = Database(self.db.engine, rel.base_name)

                rel_table = Table(rel_db, rel.table_name)

                # Set value of fkey columns to matched colums of record
                for rel_rec in rel.records:
                    if 'values' not in rel_rec:
                        continue
                    for idx, col in enumerate(rel.constrained_columns):
                        pkcol = rel.referred_columns[idx]
                        rel_rec['values'][col] = record.get_value(pkcol)

                        # Primary keys of relation may be updated by
                        # cascade if primary keys of record is updated
                        if col in rel_rec.prim_key:
                            rel_rec.prim_key[col] = record.get_value(pkcol)

                rel_table.save(rel.records)

        return result

    @measure_time
    def init_fkeys(self):
        """Store foreign keys in table object"""
        if (self.db.attrs.get("cache", None) and not self.db.config):
            self.fkeys = self.db.attrs.cache.tables[self.name].fkeys
            return
        self.fkeys = Dict()

        for fkey in self.db.refl.get_foreign_keys(self.name, self.db.schema):
            fkey = Dict(fkey)
            if fkey.referred_table not in self.db.user_tables:
                continue

            # Can't extract constraint names in SQLite
            if not fkey.name:
                fkey.name = self.name + '_'
                fkey.name += '_'.join(fkey.constrained_columns) + '_fkey'

            self.fkeys[fkey.name] = Dict(fkey)

    @measure_time
    def init_fields(self):
        """Store Dict of fields in table object"""
        if (self.db.attrs.get("cache", None) and not self.db.config):
            self.fields = self.db.attrs.cache.tables[self.name].fields
            return

        fields = Dict()
        indexes = self.get_indexes()
        indexed_cols = []
        for key, index in indexes.items():
            indexed_cols.append(index.columns[0])
        pkey = self.get_pkey()
        cols = self.db.refl.get_columns(self.name, self.db.schema)
        # contents = None if not self.db.attrs.cache \
        #     else self.db.attrs.cache.contents

        for col in cols:
            col = Dict(col)

            column = Column(self, col)
            fld = Field(self, col.name)
            field = fld.get(column)
            if field.fkey:
                condition, params = fld.get_condition()
                field.options = fld.get_options(condition, params)

            # Get info about column use if user has chosen this option
            if (
                self.db.config and self.db.config.column_use and
                col.name not in pkey.columns and
                not self.name.startswith('meta_')
                # table not in group named '...'
                # and (
                #     not contents['...'] or ('tables.' + self.name) not in \
                #     contents['...'].subitems.values()
                # )
            ):
                if col.name not in indexed_cols:
                    column.create_index(col.type_name)

                # Find if column is (largely) empty
                field.use = column.check_use()

                # if (field.use and field.datatype == "str"):
                #     field.size = column.get_size()
                #     if field.size < 256:
                #         field.element = "input[type=text]"

                if col.type_name not in ['blob', 'clob', 'text']:
                    field.frequency = column.check_frequency()

            fields[col.name] = field

        updated_idx = indexes.get(self.name + "_updated_idx", None)
        if updated_idx:
            for col in updated_idx.columns:
                fields[col].extra = "auto_update"
                fields[col].editable = False
            if len(updated_idx.columns) == 2:
                col = updated_idx.columns[1]
                fields[col].default = self.db.user
        created_idx = indexes.get(self.name + "_created_idx", None)
        if created_idx:
            for col in created_idx.columns:
                fields[col].extra = "auto"
                fields[col].editable = False
            if len(created_idx.columns) == 2:
                col = created_idx.columns[1]
                fields[col].default = self.db.user

        self.fields = fields

    @measure_time
    def init_indexes(self):
        """Store Dict of indexes as attribute of table object"""
        if self.db.attrs.get("cache", None) and not self.db.config:
            self.indexes = \
                self.db.attrs.cache.tables[self.name].indexes
            return

        indexes = Dict()

        refl_indexes = self.db.refl.get_indexes(self.name, self.db.schema)
        for index in refl_indexes:
            index = Dict(index)
            indexes[index.name] = Dict({
                'name': index.name,
                'unique': index.unique,
                'columns': index.column_names
            })

        if self.get_pkey():
            indexes[self.pkey.name] = self.pkey

        self.indexes = indexes

    def init_relations(self):
        """Store Dict of 'has many' relations as attribute of table object"""
        if hasattr(self.db, 'relations'):
            self.relations = self.db.relations[self.name]
            return
        if self.db.attrs.get("cache", None) and not self.db.config:
            self.relations = \
                self.db.attrs.cache.tables[self.name].relations
            return

        relations = Dict()

        if not hasattr(self, 'type'):
            self.get_type()

        table_name = self.name
        if self.type == 'view':
            sql = self.db.expr.view_definition()
            params = {'schema': self.db.schema, 'table': self.name}
            view_def = self.db.query(sql, params).first()[0]

            # get dialect for SQLGlot
            dialect = self.db.engine.name
            if dialect == 'mssql':
                dialect = 'tsql'
            elif dialect == 'postgresql':
                dialect = 'postgres'
            elif dialect == 'mariadb':
                dialect = 'mysql'

            table = parse_one(view_def, read=dialect).find(exp.Table)
            table_name = table.name

        for key, fkeys in self.db.refl.get_multi_foreign_keys().items():
            for fkey in fkeys:
                fkey = Dict(fkey)

                if (
                    fkey.referred_schema not in [self.db.schema, None] or
                    fkey.referred_table != table_name
                ):
                    continue

                relations[fkey.name] = Dict(fkey)
                relations[fkey.name].table = key[1]
                relations[fkey.name].schema = key[0] or self.db.schema

        # find how much the relation is used
        if self.db.config.column_use:
            for name, relation in relations.items():
                fkey_col = relation.constrained_columns[-1]

                sql = f"""
                select count(distinct({fkey_col})) from {relation.table}
                """

                count = self.db.query(sql).fetchval()

                relations[name].use = count/self.rowcount

        self.relations = relations

    def export_ddl(self, system):
        """Return ddl for table"""
        pkey = self.get_pkey()
        ddl = f"create table {self.name} (\n"
        coldefs = []
        for col in self.get_fields().values():
            expr = Expression(system)
            size = col.size
            if 'scale' in col:
                size = str(col.precision) + "," + str(col.scale)
            datatype = expr.to_native_type(col.datatype, size)
            coldef = f"    {col.name} {datatype}"
            if not col.nullable:
                coldef += " NOT NULL"
            if col.default:
                default = col.default if not col.default_expr \
                    else col.default_expr
                if (
                    col.datatype in ['str', 'date'] and
                    default[0:8] != 'CURRENT_'
                ):
                    coldef += " DEFAULT '" + default + "'"
                else:
                    coldef += " DEFAULT " + default
            coldefs.append(coldef)
        ddl += ",\n".join(coldefs)
        if (pkey and pkey.columns != ['rowid']):
            ddl += ",\n" + "    primary key (" + ", ".join(pkey.columns) + ")"

        for fkey in self.get_fkeys().values():
            ddl += ",\n    foreign key ("
            ddl += ", ".join(fkey.constrained_columns) + ") "
            ddl += f"references {fkey.referred_table}("
            ddl += ", ".join(fkey.referred_columns) + ")"
        ddl += ");\n\n"

        for idx in self.get_indexes().values():
            if idx.columns == pkey.columns:
                continue
            ddl += "create "
            if idx.unique:
                ddl += "unique "
            # Only mysql has index within table namespace
            idx_name = idx.name
            if idx.name == '_'.join(idx.columns):
                idx_name = self.name + '_' + idx.name
            ddl += f"index {idx_name} on {self.name} ("
            ddl += ",".join(idx.columns) + ");\n"

        return ddl

    def export_records(self, select_recs: bool, fkey: dict):
        """Export records as sql

        Parameters:
        select_recs: If records should be selected from existing database
        """
        insert = '\n'
        if fkey and self.db.engine.name in ['mysql', 'postgresql', 'sqlite']:
            cols = self.db.refl.get_columns(self.name, self.db.schema)
            colnames = []
            for col in cols:
                colnames.append(col['name'])

            select = ', '.join(colnames)
            fkey_cc = fkey['constrained_columns'][0]
            fkey_rc = fkey['referred_columns'][0]
            sql = f"""
            with recursive tbl_data as (
                select {self.name}.*, 1 as level
                from {self.name}
                where {fkey_cc} is null

                union all

                select this.*, prior.level + 1
                from tbl_data prior
                inner join {self.name} this
                   on this.{fkey_cc} = prior.{fkey_rc}
            )
            select {select}
            from tbl_data
            order by level
            """
        else:
            sql = f"select * from {self.name}"

        rows = self.db.query(sql).mappings()
        cols = self.get_fields()

        if select_recs:
            db_name = self.db.name.split('.')[0]
            insert += f'insert into {self.name}\n'
            insert += 'select ' + ', '.join(rows.keys())
            insert += f' from {db_name}.{self.name};\n\n'
        else:
            for row in rows:
                insert += f'insert into {self.name} values ('
                for colname, val in row.items():
                    col = cols[colname]
                    if (self.name == 'meta_data' and colname == 'cache'):
                        val = ''
                    if type(val) is str:
                        val = "'" + val.replace("'", "''") + "'"
                    elif isinstance(val, datetime.date):
                        val = "'" + str(val) + "'"
                    elif (col.datatype == 'bool' and type(val) is int):
                        val = 'FALSE' if val == 0 else 'TRUE'
                    elif val is None:
                        val = 'null'
                    insert += str(val) + ','
                insert = insert[:-1] + ");\n"

        return insert

    def convert(self, colname, from_format, to_format):

        select = ', '.join(self.tbl.pkey.columns)

        sql = f"""
        select {select}, {colname}
        from {self.tbl.name}
        """

        cursor = self.db.query(sql)
        rows = cursor.fetchall()
        colnames = [col[0] for col in cursor.description]
        cursor2 = self.db.cnxn.cursor()
        for row in rows:
            row = (dict(zip(colnames, row)))
            wheres = []
            params = []
            for key in self.tbl.pkey.columns:
                wheres.append(key + '=?')
                params.append(row[key])

            where = ', '.join(wheres)

            try:
                text = pypandoc.convert_text(row[colname], to_format,
                                             format=from_format)
            except Exception as e:
                print('kunne ikke konvertere ' + params[-1])
                print(e.message)

            params.insert(0, text)

            sql = f"""
            update {self.tbl.name}
            set {self.name} = ?
            where {where}
            """

            cursor2.execute(sql, params)

        cursor2.commit()

        return 'success'
