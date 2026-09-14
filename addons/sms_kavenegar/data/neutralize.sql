-- A neutralized copy must never send real SMS or hold the production key.
UPDATE res_company
   SET sms_kavenegar_enabled = false,
       sms_kavenegar_api_key = NULL;
