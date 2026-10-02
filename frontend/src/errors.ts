const tencentHints: Record<string, string> = {
  'ResourceUnavailable.NotExist': '可能是服务未开通或计费状态异常；请在腾讯云控制台核对混元生3D开通状态',
  'ResourceUnavailable.InArrears': '账号可能欠费；请检查腾讯云账单',
  'ResourceUnavailable.LowBalance': '账户余额不足；请检查腾讯云账户余额',
  'AuthFailure.InvalidSecretId': 'Secret ID 无效；请在设置页核对密钥',
  'AuthFailure.SignatureFailure': '签名校验失败；请核对 Secret ID 和 Secret Key',
  UnsupportedRegion: '所选地域不支持此接口；请核对设置页中的地域',
  UnauthorizedOperation: '账号无调用权限；请检查 CAM 授权和服务开通状态',
  RequestLimitExceeded: '请求超过频率限制；请稍后再试',
};

const poseHints: Record<string, string> = {
  InvalidApiKey: 'API Key 无效；请核对密钥和服务地址',
  invalid_api_key: 'API Key 无效；请核对密钥和服务地址',
  'AccessDenied.Unpurchased': '百炼服务或模型尚未开通；请检查账号权限',
  ModelNotFound: '模型不可用；请核对模型名称和授权',
  'Throttling.RateQuota': '请求触发限流；请稍后再试',
  'Throttling.AllocationQuota': '可用额度不足；请检查百炼配额',
};

export function explainJobError(message: string, stage?: string): string {
  if (stage === 'rig' && /腾讯云错误 InvalidParameter/.test(message)) {
    const hint = '绑骨接口未接受输入模型；请核对角色姿态和 GLB 文件要求，具体原因可凭 RequestId 向腾讯云查询';
    const code = message.match(/腾讯云错误 InvalidParameter[A-Za-z0-9_.-]*/)?.[0];
    const requestId = message.match(/；RequestId=[A-Za-z0-9_.-]+/)?.[0] || '';
    return `${code}：${hint}${requestId}`;
  }
  const tencent = message.match(/腾讯云错误 ([A-Za-z0-9_.-]+)/);
  if (tencent && !message.includes(`${tencent[1]}：`)) {
    const hint = tencentHints[tencent[1]] ||
      (tencent[1].startsWith('InvalidParameter') ? '请求参数不被接受；请核对当前步骤的输入与接口要求' : '请在腾讯云控制台凭 RequestId 查询原因');
    return message.replace(tencent[0], `${tencent[0]}：${hint}`);
  }
  const pose = message.match(/姿势 API 错误 ([A-Za-z0-9_.-]+)/);
  if (pose && !message.includes(`${pose[1]}：`)) {
    return message.replace(pose[0], `${pose[0]}：${poseHints[pose[1]] || '请在百炼控制台核对模型和账号权限'}`);
  }
  return message;
}
