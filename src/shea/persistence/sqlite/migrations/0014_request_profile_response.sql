-- 0014_request_profile_response: the Request records which profile it was
-- made under (previously smuggled through Intent.parameters) and the reply
-- it received, so conversation history exists independently of any Task.

ALTER TABLE requests ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'system';
ALTER TABLE requests ADD COLUMN response TEXT;