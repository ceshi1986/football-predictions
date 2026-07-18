// Debug version - echo back the event structure
exports.handler = async function(event, context, callback) {
  let eventStr = '';
  try {
    if (Buffer.isBuffer(event)) {
      eventStr = event.toString('utf8');
    } else if (typeof event === 'string') {
      eventStr = event;
    } else {
      eventStr = JSON.stringify(event);
    }
  } catch(e) {
    eventStr = 'Error: ' + e.message;
  }
  
  callback(null, {
    statusCode: 200,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      eventPreview: eventStr.substring(0, 2000),
      eventType: typeof event,
      isBuffer: Buffer.isBuffer(event),
      keys: Object.keys(typeof event === 'object' && event ? event : {})
    })
  });
};
