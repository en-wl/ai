#!/bin/sh

exec sqlite3 -init /dev/null data.db <<EOF
.mode tabe
.header off
select json_extract(rd.response, '$.choices[0].message.content') from raw_data as rd where req_id=$1
EOF
