const databaseName = 'autopath-budget';
const storeName = 'sqliteFiles';
let connection;

function openDatabase() {
  if (!connection) {
    connection = new Promise((resolve, reject) => {
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(storeName)) {
          request.result.createObjectStore(storeName, {keyPath: 'id'});
        }
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('Хранилище занято другой вкладкой'));
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => {
          database.close();
          connection = null;
        };
        resolve(database);
      };
    }).catch(error => {
      connection = null;
      throw error;
    });
  }
  return connection;
}

export async function loadBytes() {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(storeName, 'readonly');
    const request = transaction.objectStore(storeName).get('current');
    let record;
    request.onsuccess = () => { record = request.result; };
    transaction.oncomplete = () => {
      if (!record) resolve(null);
      else if (record.dbVersion !== 1 || !(record.bytes instanceof Uint8Array)) {
        reject(new Error('Сохранённая база имеет неподдерживаемый формат'));
      } else resolve(record.bytes);
    };
    transaction.onerror = () => reject(transaction.error || request.error);
    transaction.onabort = () => reject(transaction.error || new Error('Чтение прервано'));
  });
}

export async function saveBytes(bytes) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(storeName, 'readwrite');
    transaction.objectStore(storeName).put({id: 'current', dbVersion: 1, bytes: new Uint8Array(bytes)});
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error || new Error('Не удалось записать базу'));
    transaction.onabort = () => reject(transaction.error || new Error('Запись прервана'));
  });
}
