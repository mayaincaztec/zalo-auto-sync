const { Zalo, ThreadType } = require('zca-js');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const COOKIE_FILE = path.join(__dirname, 'cookie.json');
const LOG_FILE = path.join(__dirname, 'bridge.log');
const DOWNLOAD_DIR = path.join(__dirname, 'downloads');

let api = null;
let messageCache = new Map();
let messageIds = new Map();
let httpOldMsgsBroken = new Set();

// Bound per-group cache to avoid unbounded RAM growth.
const MAX_CACHE_PER_GROUP = 5000;

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  fs.appendFileSync(LOG_FILE, line, 'utf-8');
}

function send(type, payload) {
  const msg = JSON.stringify({ type, ...payload }) + '\n';
  fs.writeSync(1, msg);
}

function respond(id, cmd, status, data) {
  send('response', { id, cmd, status, data });
}

function emit(event, data) {
  send('event', { event, data });
}

function getCachedMessages(groupId) {
  return (messageCache.get(groupId) || []).slice();
}

function streamToFile(response, dest) {
  return new Promise((resolve, reject) => {
    const writer = fs.createWriteStream(dest);
    const reader = response.body.getReader();
    const pump = () => {
      reader.read().then(({ done, value }) => {
        if (done) {
          writer.end();
          return;
        }
        if (!writer.write(Buffer.from(value))) {
          writer.once('drain', pump);
        } else {
          pump();
        }
      }).catch(err => {
        writer.destroy();
        reject(err);
      });
    };
    writer.on('finish', () => {
      try {
        const size = fs.statSync(dest).size;
        resolve(size);
      } catch (err) {
        reject(err);
      }
    });
    writer.on('error', reject);
    pump();
  });
}

function addToCache(groupId, msgs) {
  let existing = messageCache.get(groupId);
  let ids = messageIds.get(groupId);
  if (!existing || !ids) {
    existing = existing || [];
    messageCache.set(groupId, existing);
    ids = new Set(existing.map(m => m.data && m.data.msgId));
    messageIds.set(groupId, ids);
  }
  for (const msg of msgs) {
    if (!msg.data) continue;
    const mid = msg.data.msgId;
    if (ids.has(mid)) continue;
    existing.push(msg);
    ids.add(mid);
  }
  if (existing.length > MAX_CACHE_PER_GROUP) {
    const drop = existing.splice(0, existing.length - MAX_CACHE_PER_GROUP);
    for (const m of drop) {
      if (m.data) ids.delete(m.data.msgId);
    }
  }
}

// Fetch group history over HTTP with progressively larger page sizes so the
// cache reaches back far enough to cover the last processed msgId. Returns the
// number of (newly added) messages. Throws on network/API failure so the caller
// can blacklist the group and fall back to WebSocket. Does nothing if the group
// is already blacklisted.
async function httpCatchUp(groupId, lastMsgId, initialCount) {
  if (!groupId || httpOldMsgsBroken.has(groupId)) return 0;
  let count = initialCount || 300;
  let totalAdded = 0;
  for (let attempt = 0; attempt < 6; attempt++) {
    const result = await api.getGroupChatHistory(groupId, count);
    const msgs = (result && result.groupMsgs) || [];
    const before = messageIds.has(groupId) ? messageIds.get(groupId).size : 0;
    addToCache(groupId, msgs);
    const after = messageIds.has(groupId) ? messageIds.get(groupId).size : 0;
    totalAdded += (after - before);

    // Stop when we have no more old messages, or when the cache already
    // reaches back past the persisted cursor (nothing missed between runs).
    const more = (result && result.more) || 0;
    const reachedCursor = lastMsgId != null &&
      msgs.some(m => m.data && String(m.data.msgId) <= String(lastMsgId));
    if (more <= 0 || reachedCursor) break;

    count = Math.min(count * 2, MAX_CACHE_PER_GROUP);
    if (count === MAX_CACHE_PER_GROUP) break;
  }
  log(`httpCatchUp ${groupId}: fetched up to ${count}, added ${totalAdded}`);
  return totalAdded;
}

let reconnectTimer = null;

function startListener() {
  if (!api || !api.listener) return;
  if (api.listener.ws) return;
  try {
    api.listener.start({ retryOnClose: false });
    log('Listener (re)started');
  } catch (err) {
    log(`Listener start error: ${err.message}, retrying in 10s`);
    reconnectTimer = setTimeout(startListener, 10000);
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    startListener();
  }, 5000);
}

function setupListeners(apiInstance) {
  apiInstance.listener.on('connected', () => {
    log('WebSocket connected');
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    emit('connected', {});
  });
  apiInstance.listener.on('disconnected', (code, reason) => {
    log(`WebSocket disconnected: ${code} ${reason}`);
    emit('disconnected', { code, reason });
    scheduleReconnect();
  });
  apiInstance.listener.on('closed', (code, reason) => {
    log(`WebSocket closed: ${code} ${reason}`);
    scheduleReconnect();
  });
  apiInstance.listener.on('message', (msg) => {
    if (msg.type !== ThreadType.Group) return;
    addToCache(msg.threadId, [msg]);
    emit('new_message', {
      groupId: msg.threadId,
      msgId: msg.data.msgId,
      msgType: msg.data.msgType,
      sender: msg.data.dName,
      timestamp: parseInt(msg.data.ts) || Date.now(),
      content: msg.data.content
    });
  });
  apiInstance.listener.on('old_messages', (messages, type) => {
    if (type !== ThreadType.Group) return;
    for (const msg of messages) {
      addToCache(msg.threadId, [msg]);
    }
    log(`Cached ${messages.length} old messages`);
  });
  apiInstance.listener.on('error', (err) => {
    log(`Listener error: ${String(err)}`);
  });
}

async function doQrLogin() {
  log('Starting QR login...');
  const zalo = new Zalo({ selfListen: true });
  try {
    log('Before loginQR call');
    api = await zalo.loginQR(
      { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' },
      (event) => {
        const t = event.type;
        log(`QR event type=${t}`);
        if (t === 0) {
          const imgData = event.data && event.data.image;
          if (imgData) {
            fs.writeFileSync(path.join(__dirname, 'qr.png'), Buffer.from(imgData, 'base64'));
            emit('qrcode', { image: imgData, code: event.data && event.data.code });
          }
        } else if (t === 1) {
          emit('qrcode_expired', {});
        } else if (t === 2) {
          emit('scanned', { name: event.data && event.data.display_name });
        } else if (t === 3) {
          emit('qrcode_declined', {});
        } else if (t === 4) {
          const info = event.data;
          if (info) {
            fs.writeFileSync(COOKIE_FILE, JSON.stringify({
              cookie: info.cookie, imei: info.imei, userAgent: info.userAgent
            }, null, 2), 'utf-8');
            log('Cookie saved');
          }
        }
      }
    );
    log('QR login OK');
    log(`API object: ${typeof api}, has listener: ${!!(api && api.listener)}`);
    emit('login_ok', { method: 'qr' });
    setupListeners(api);
    startListener();
  } catch (err) {
    log(`Login error: ${err.message} stack: ${(err.stack || '').split('\n').slice(0,3).join(' | ')}`);
    emit('login_error', { message: err.message });
    api = null;
  }
  log('doQrLogin finished');
}

async function dispatch(id, command, data) {
  switch (command) {
    case 'login': {
      if (fs.existsSync(COOKIE_FILE)) {
        try {
          const cookieData = JSON.parse(fs.readFileSync(COOKIE_FILE, 'utf-8'));
          log('Trying saved cookie...');
          const zalo = new Zalo({ selfListen: true });
          api = await zalo.login(cookieData);
          log('Cookie login OK');
          emit('login_ok', { method: 'cookie' });
          setupListeners(api);
          startListener();
          respond(id, 'login', 'ok', { method: 'cookie' });
          return;
        } catch (err) {
          log(`Cookie failed: ${err.message}, fallback to QR`);
          api = null;
        }
      }
      doQrLogin();
      respond(id, 'login', 'qr_started', {});
      break;
    }
    case 'get_status': {
      const groups = Array.from(messageCache.entries()).map(([g, msgs]) => ({
        groupId: g, count: msgs.length
      }));
      respond(id, 'get_status', 'ok', {
        loggedIn: api !== null, cachedGroups: groups
      });
      break;
    }
    case 'get_groups': {
      if (!api) { respond(id, 'get_groups', 'error', { message: 'Not logged in' }); break; }
      try {
        const result = await api.getAllGroups();
        const groupIds = Object.keys(result.gridVerMap || {});
        respond(id, 'get_groups', 'ok', { groupIds });
      } catch (err) {
        respond(id, 'get_groups', 'error', { message: err.message });
      }
      break;
    }
    case 'get_group_info': {
      if (!api) { respond(id, 'get_group_info', 'error', { message: 'Not logged in' }); break; }
      try {
        const result = await api.getGroupInfo(data.groupId);
        respond(id, 'get_group_info', 'ok', result);
      } catch (err) {
        respond(id, 'get_group_info', 'error', { message: err.message });
      }
      break;
    }
    case 'find_group': {
      if (!api) { respond(id, 'find_group', 'error', { message: 'Not logged in' }); break; }
      const targetName = data.name;
      if (!targetName) { respond(id, 'find_group', 'error', { message: 'No name provided' }); break; }
      try {
        const groupsResult = await api.getAllGroups();
        const groupIds = Object.keys(groupsResult.gridVerMap || {});
        log(`find_group: ${groupIds.length} total groups, searching for '${targetName}'`);
        let foundId = null;
        for (const gid of groupIds) {
          try {
            const infoResult = await api.getGroupInfo(gid);
            const gridInfoMap = (infoResult && infoResult.gridInfoMap) || {};
            const info = gridInfoMap[gid] || {};
            const name = info.name || '';
            if (name === targetName) {
              foundId = gid;
              log(`find_group: found '${targetName}' => ${gid}`);
              break;
            }
          } catch (e) {
            log(`find_group: skip ${gid}: ${e.message}`);
          }
        }
        if (foundId) {
          respond(id, 'find_group', 'ok', { groupId: foundId });
        } else {
          respond(id, 'find_group', 'error', { message: `Group '${targetName}' not found` });
        }
      } catch (err) {
        log(`find_group error: ${err.message}`);
        respond(id, 'find_group', 'error', { message: err.message });
      }
      break;
    }
    case 'get_group_messages': {
      const groupId = data.groupId;
      const cached = getCachedMessages(groupId);
      const filtered = cached.filter(msg => {
        if (!msg.data) return false;
        if (data.types && data.types.length > 0) {
          return data.types.includes(msg.data.msgType);
        }
        return true;
      });
      const since = data.since_msg_id ? Number(data.since_msg_id) : null;
      const delta = since ? filtered.filter(msg => Number(msg.data.msgId) > since) : filtered;
      const messages = delta.map(msg => ({
        msgId: msg.data.msgId,
        msgType: msg.data.msgType,
        sender: msg.data.dName,
        senderId: msg.data.uidFrom,
        timestamp: parseInt(msg.data.ts) || Date.now(),
        content: msg.data.content
      }));
      respond(id, 'get_group_messages', 'ok', {
        groupId,
        messages,
        total: filtered.length,
        new_count: messages.length,
        since_msg_id: data.since_msg_id || null
      });
      break;
    }
    case 'request_old_messages': {
      if (!api) { respond(id, 'request_old_messages', 'error', { message: 'Not logged in' }); break; }
      const groupId = data.groupId;
      const count = data.count || 300;
      const lastMsgId = data.lastMsgId || null;
      if (groupId && !httpOldMsgsBroken.has(groupId)) {
        try {
          const added = await httpCatchUp(groupId, lastMsgId, count);
          respond(id, 'request_old_messages', 'ok', { method: 'http', count: added });
          break;
        } catch (err) {
          httpOldMsgsBroken.add(groupId);
          log(`request_old_messages HTTP error: ${err.message}; disabling HTTP path for this group, falling back to WebSocket`);
        }
      }
      try {
        api.listener.requestOldMessages(ThreadType.Group, lastMsgId || undefined);
        respond(id, 'request_old_messages', 'ok', { method: 'ws' });
      } catch (err) {
        respond(id, 'request_old_messages', 'error', { message: err.message });
      }
      break;
    }
    case 'get_chat_history': {
      if (!api) { respond(id, 'get_chat_history', 'error', { message: 'Not logged in' }); break; }
      try {
        const result = await api.getGroupChatHistory(data.groupId, data.count || 50);
        respond(id, 'get_chat_history', 'ok', result);
      } catch (err) {
        respond(id, 'get_chat_history', 'error', { message: err.message });
      }
      break;
    }
    case 'get_members': {
      if (!api) { respond(id, 'get_members', 'error', { message: 'Not logged in' }); break; }
      const groupId = data.groupId;
      if (!groupId) { respond(id, 'get_members', 'error', { message: 'No groupId' }); break; }
      try {
        const infoRes = await api.getGroupInfo(groupId);
        const grid = (infoRes && infoRes.gridInfoMap) || {};
        const info = grid[groupId] || {};
        const allIds = info.memberIds || [];
        const adminIds = info.adminIds || [];
        const creatorId = info.creatorId || '';

        const nameMap = {};
        for (const m of (info.currentMems || [])) {
          nameMap[m.id] = m.dName || m.zaloName || '';
        }

        const lastTs = {};
        const msgCount = {};
        const histCount = data.count || 2000;
        try {
          const hist = await api.getGroupChatHistory(groupId, histCount);
          for (const msg of (hist && hist.groupMsgs) || []) {
            const d = msg && msg.data;
            if (!d || !d.uidFrom) continue;
            const uid = d.uidFrom;
            const ts = parseInt(d.ts) || 0;
            if (!lastTs[uid] || ts > lastTs[uid]) lastTs[uid] = ts;
            msgCount[uid] = (msgCount[uid] || 0) + 1;
          }
        } catch (histErr) {
          log(`get_members history error: ${histErr.message}`);
        }

        const members = allIds.map(uid => ({
          id: uid,
          name: nameMap[uid] || '',
          isAdmin: adminIds.includes(uid) || uid === creatorId,
          isCreator: uid === creatorId,
          lastActive: lastTs[uid] || 0,
          msgCount: msgCount[uid] || 0
        }));

        respond(id, 'get_members', 'ok', {
          groupId,
          groupName: info.name || '',
          totalMember: members.length,
          members
        });
      } catch (err) {
        respond(id, 'get_members', 'error', { message: err.message });
      }
      break;
    }
    case 'kick_members': {
      if (!api) { respond(id, 'kick_members', 'error', { message: 'Not logged in' }); break; }
      const groupId = data.groupId;
      const memberIds = (data.memberIds || []).filter(Boolean);
      if (!groupId || memberIds.length === 0) {
        respond(id, 'kick_members', 'error', { message: 'No groupId or memberIds' }); break;
      }
      try {
        const res = await api.removeUserFromGroup(memberIds, groupId);
        respond(id, 'kick_members', 'ok', { errorMembers: (res && res.errorMembers) || [] });
      } catch (err) {
        respond(id, 'kick_members', 'error', { message: err.message });
      }
      break;
    }
    case 'download': {
      const { url, destination } = data;
      if (!url) { respond(id, 'download', 'error', { message: 'No URL' }); break; }
      try {
        const basename = path.basename(url.split('?')[0]) || 'download.bin';
        const dest = destination || path.join(DOWNLOAD_DIR, basename);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        log(`Downloading ${url}`);
        respond(id, 'download', 'ok', { started: true, path: dest });
        (async () => {
          try {
            const response = await fetch(url);
            if (!response.ok) {
              emit('download_complete', { id, path: dest, error: `HTTP ${response.status}` });
              return;
            }
            const size = await streamToFile(response, dest);
            emit('download_complete', { id, path: dest, size });
          } catch (err) {
            emit('download_complete', { id, path: dest, error: err.message });
          }
        })();
      } catch (err) {
        respond(id, 'download', 'error', { message: err.message });
      }
      break;
    }
    default:
      respond(id, command, 'error', { message: 'Unknown: ' + command });
  }
}

async function start() {
  log('Bridge started');
  emit('ready', {});

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false
  });

  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const cmd = JSON.parse(line);
      const { id, command, data } = cmd;
      log(`cmd: ${command} (${id})`);
      await dispatch(id, command, data || {});
    } catch (err) {
      log(`Parse error: ${err.message}`);
    }
  }
}

start().catch(err => {
  log(`Fatal: ${err.message}`);
  process.exit(1);
});
