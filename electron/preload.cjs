const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dikeyDesktop', Object.freeze({
  retry: () => ipcRenderer.invoke('desktop:retry'),
  openLogs: () => ipcRenderer.invoke('desktop:open-logs'),
}));
