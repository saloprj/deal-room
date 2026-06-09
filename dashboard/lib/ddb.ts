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
};

export async function latestCall(): Promise<Call | null> {
  const out = await ddb.send(new ScanCommand({ TableName: TABLE }));
  const items = (out.Items || []) as Call[];
  if (!items.length) return null;
  items.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  return items[0];
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

export async function addNudge(id: string, text: string) {
  const entry = { speaker: "operator", text, ts: Math.floor(Date.now() / 1000) };
  await ddb.send(new UpdateCommand({
    TableName: TABLE, Key: { call_id: id },
    UpdateExpression:
      "SET command = :c, operator_note = :n, transcript = list_append(if_not_exists(transcript, :e), :t), updated_at = :u",
    ExpressionAttributeValues: { ":c": "nudge", ":n": text, ":t": [entry], ":e": [], ":u": Math.floor(Date.now() / 1000) },
  }));
}
