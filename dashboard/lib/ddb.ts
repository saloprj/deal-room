import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, PutCommand, ScanCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";

const REGION = process.env.AWS_DEFAULT_REGION || "us-east-1";
export const TABLE = process.env.DDB_TABLE || "dealroom_calls";

const base = new DynamoDBClient({
  region: REGION,
  credentials: {
    accessKeyId: process.env.AWS_ACCESS_KEY_ID!,
    secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY!,
    sessionToken: process.env.AWS_SESSION_TOKEN,
  },
});
export const ddb = DynamoDBDocumentClient.from(base);

export type Call = {
  call_id: string;
  status: string;
  transcript: { speaker: string; text: string; ts: number }[];
  command: string;
  approved: boolean;
  payment_status: string;
  checkout_url: string;
  updated_at: number;
  chat_id?: string;
  chat_title?: string;
};

export type Chat = { chat_id: string; title: string; members?: number };

const CHATS_KEY = "CHATS#index";

export async function latestCall(): Promise<Call | null> {
  const out = await ddb.send(new ScanCommand({ TableName: TABLE }));
  // Only real call rows (skip the chat-index control item).
  const items = (out.Items || []).filter((i: any) => String(i.call_id).startsWith("call-")) as Call[];
  if (!items.length) return null;
  items.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  return items[0];
}

// The worker (Telethon, acct256) publishes the group chats it can present into.
export async function listChats(): Promise<Chat[]> {
  const out = await ddb.send(new GetCommand({ TableName: TABLE, Key: { call_id: CHATS_KEY } }));
  return (((out.Item as any)?.chats as Chat[]) || []).slice().sort((a, b) => a.title.localeCompare(b.title));
}

// Dispatch the agent into a chat: create a dispatch-requested call the EC2
// dispatcher picks up (joins that chat's voice call + presents the deck).
export async function dispatchToChat(chatId: string, title: string): Promise<Call> {
  const id = `call-${Date.now()}`;
  const item: Call = {
    call_id: id, status: "dispatch_requested", transcript: [], command: "start",
    approved: false, payment_status: "none", checkout_url: "", updated_at: Math.floor(Date.now() / 1000),
    chat_id: String(chatId), chat_title: title,
  };
  await ddb.send(new PutCommand({ TableName: TABLE, Item: item }));
  return item;
}

export async function getCall(id: string): Promise<Call | null> {
  const out = await ddb.send(new GetCommand({ TableName: TABLE, Key: { call_id: id } }));
  return (out.Item as Call) || null;
}

export async function createCall(id: string) {
  const item: Call = {
    call_id: id, status: "starting", transcript: [], command: "start",
    approved: false, payment_status: "none", checkout_url: "", updated_at: Math.floor(Date.now() / 1000),
  };
  await ddb.send(new PutCommand({ TableName: TABLE, Item: item }));
  return item;
}

export async function setApproved(id: string) {
  await ddb.send(new UpdateCommand({
    TableName: TABLE, Key: { call_id: id },
    UpdateExpression: "SET approved = :t, command = :c, updated_at = :u",
    ExpressionAttributeValues: { ":t": true, ":c": "approve", ":u": Math.floor(Date.now() / 1000) },
  }));
}

export async function setRejected(id: string) {
  await ddb.send(new UpdateCommand({
    TableName: TABLE, Key: { call_id: id },
    UpdateExpression: "SET approved = :f, command = :c, #s = :live, updated_at = :u",
    ExpressionAttributeNames: { "#s": "status" },
    ExpressionAttributeValues: { ":f": false, ":c": "reject", ":live": "live", ":u": Math.floor(Date.now() / 1000) },
  }));
}

// Ask the agent a question. Creates an interactive session if none is given.
// Sets pending_q; the EC2 responder runs the brain and appends the answer.
export async function askAgent(callId: string | undefined, text: string): Promise<string> {
  let id = callId;
  if (!id) {
    id = `call-${Date.now()}`;
    await ddb.send(new PutCommand({
      TableName: TABLE,
      Item: {
        call_id: id, status: "interactive", transcript: [], command: "none",
        approved: false, payment_status: "none", checkout_url: "",
        updated_at: Math.floor(Date.now() / 1000),
      },
    }));
  }
  await ddb.send(new UpdateCommand({
    TableName: TABLE, Key: { call_id: id },
    UpdateExpression: "SET command = :c, pending_q = :q, updated_at = :u",
    ExpressionAttributeValues: { ":c": "ask", ":q": text, ":u": Math.floor(Date.now() / 1000) },
  }));
  return id;
}

export async function addNudge(id: string, text: string) {
  const entry = { speaker: "operator", text, ts: Math.floor(Date.now() / 1000) };
  await ddb.send(new UpdateCommand({
    TableName: TABLE, Key: { call_id: id },
    UpdateExpression:
      "SET command = :c, operator_note = :n, transcript = list_append(if_not_exists(transcript, :e), :t), updated_at = :u",
    ExpressionAttributeValues: { ":c": "nudge", ":n": text, ":t": [entry], ":e": [], ":u": Math.floor(Date.now() / 1000) },
  }));
}
