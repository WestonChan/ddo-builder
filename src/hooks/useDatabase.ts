import { useEffect, useState } from 'react'
import initSqlJs from 'sql.js'
import type { Database } from 'sql.js'
import sqlWasm from 'sql.js/dist/sql-wasm.wasm?url'

const DB_URL = import.meta.env.BASE_URL + 'data/ddo.db'

// Singleton promise — DB is fetched and initialized only once per page load.
let _dbPromise: Promise<Database> | null = null

function getDb(): Promise<Database> {
  if (!_dbPromise) {
    _dbPromise = initSqlJs({ locateFile: () => sqlWasm }).then((SQL) =>
      fetch(DB_URL)
        .then((r) => {
          if (!r.ok) throw new Error(`Failed to fetch DB: ${r.status} ${r.statusText}`)
          return r.arrayBuffer()
        })
        .then((buf) => new SQL.Database(new Uint8Array(buf))),
    )
  }
  return _dbPromise
}

interface DatabaseState {
  db: Database | null
  loading: boolean
  error: Error | null
}

export function useDatabase(): DatabaseState {
  const [state, setState] = useState<DatabaseState>({ db: null, loading: true, error: null })

  useEffect(() => {
    let cancelled = false

    getDb()
      .then((db) => {
        if (!cancelled) setState({ db, loading: false, error: null })
      })
      .catch((err) => {
        if (!cancelled)
          setState({
            db: null,
            loading: false,
            error: err instanceof Error ? err : new Error(String(err)),
          })
      })

    return () => {
      cancelled = true
    }
  }, [])

  return state
}
