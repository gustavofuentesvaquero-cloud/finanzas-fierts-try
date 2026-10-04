import Database from "better-sqlite3";
import path from "path";

// Localizacion de la base de datos de SQLite generada por el backend de Python
const DB_PATH = process.env.DATABASE_PATH || path.resolve(process.cwd(), "..", "backend", "data", "backtesting.db");

let dbInstance: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!dbInstance) {
    dbInstance = new Database(DB_PATH, { readonly: true, fileMustExist: true });
    dbInstance.pragma("journal_mode = WAL");
  }
  return dbInstance;
}
