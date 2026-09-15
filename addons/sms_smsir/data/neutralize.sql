-- A neutralized copy must never send real SMS or hold the production key.
UPDATE res_company
   SET sms_smsir_enabled = false,
       sms_smsir_api_key = NULL;
