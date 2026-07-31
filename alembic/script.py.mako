<%!
import re

%>"""
${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade(engine_name: str = "") -> None:
    """
    依據指定的引擎名稱，執行對應的資料庫升級操作。

    Args:
        engine_name (str): 資料庫引擎名稱 ("auth" 或 "crawler")。預設為空字串。
    """
    globals().get(f"upgrade_{engine_name}", lambda: None)()


def downgrade(engine_name: str = "") -> None:
    """
    依據指定的引擎名稱，執行對應的資料庫降級操作。

    Args:
        engine_name (str): 資料庫引擎名稱 ("auth" 或 "crawler")。預設為空字串。
    """
    globals().get(f"downgrade_{engine_name}", lambda: None)()

<%
    db_names = config.get_main_option("databases")
%>

## generate an "upgrade_<xyz>() / downgrade_<xyz>()" function
## for each database name in the ini file.

% for db_name in re.split(r',\s*', db_names):

def upgrade_${db_name}() -> None:
    """
    執行 ${db_name.capitalize()} 資料庫的升級操作。
    """
    ${context.get("%s_upgrades" % db_name, "pass")}


def downgrade_${db_name}() -> None:
    """
    執行 ${db_name.capitalize()} 資料庫的降級操作。
    """
    ${context.get("%s_downgrades" % db_name, "pass")}

% endfor
