"""
Emby API 客户端

支持：
- 推送刮削结果到 Emby
- 刷新媒体库
- 获取媒体信息
- 更新元数据
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class EmbyItemType(str, Enum):
    """Emby 项目类型"""
    MOVIE = "Movie"
    SERIES = "Series"
    EPISODE = "Episode"
    PERSON = "Person"
    FOLDER = "Folder"


@dataclass
class EmbyConfig:
    """Emby 配置"""
    url: str                    # Emby 服务器地址
    api_key: str                # API Key
    user_id: Optional[str] = None  # 用户 ID（某些操作需要）
    timeout: int = 30           # 超时时间（秒）
    verify_ssl: bool = True     # 是否验证 SSL


@dataclass
class EmbyItem:
    """Emby 媒体项目"""
    id: str
    name: str
    type: EmbyItemType
    path: Optional[str] = None
    overview: Optional[str] = None
    genres: list[str] = None
    actors: list[dict] = None
    studios: list[str] = None
    premiere_date: Optional[datetime] = None
    official_rating: Optional[str] = None
    community_rating: Optional[float] = None
    image_primary: Optional[str] = None
    image_thumb: Optional[str] = None
    image_backdrop: Optional[str] = None


class EmbyClient:
    """
    Emby API 客户端
    
    文档：https://dev.emby.media/doc/restapi/
    """
    
    def __init__(self, config: EmbyConfig):
        """
        初始化
        
        Args:
            config: Emby 配置
        """
        self.config = config
        self.base_url = config.url.rstrip('/')
        self.api_key = config.api_key
        self.headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json',
        }
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        发送请求
        
        Args:
            method: HTTP 方法
            endpoint: API 端点
            params: 查询参数
            json_data: JSON 数据
            
        Returns:
            响应数据
        """
        url = f"{self.base_url}{endpoint}"
        
        async with httpx.AsyncClient(
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
        ) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data,
                )
                response.raise_for_status()
                
                if response.content:
                    return response.json()
                return None
            
            except httpx.HTTPError as e:
                logger.error(f"Emby API error: {e}")
                raise
    
    async def get_system_info(self) -> dict:
        """
        获取系统信息
        
        Returns:
            系统信息
        """
        return await self._request('GET', '/System/Info')
    
    async def get_user_views(self, user_id: Optional[str] = None) -> list[dict]:
        """
        获取用户媒体库视图
        
        Args:
            user_id: 用户 ID
            
        Returns:
            媒体库列表
        """
        user_id = user_id or self.config.user_id
        if not user_id:
            raise ValueError("User ID is required")
        
        data = await self._request('GET', f'/Users/{user_id}/Views')
        return data.get('Items', [])
    
    async def search_items(
        self,
        search_term: str,
        item_types: Optional[list[EmbyItemType]] = None,
        limit: int = 20,
    ) -> list[EmbyItem]:
        """
        搜索媒体
        
        Args:
            search_term: 搜索关键词
            item_types: 项目类型过滤
            limit: 返回数量限制
            
        Returns:
            搜索结果列表
        """
        params = {
            'SearchTerm': search_term,
            'Limit': limit,
            'Recursive': 'true',
        }
        
        if item_types:
            params['IncludeItemTypes'] = ','.join(t.value for t in item_types)
        
        data = await self._request('GET', '/Items', params=params)
        
        items = []
        for item in data.get('Items', []):
            items.append(EmbyItem(
                id=item.get('Id'),
                name=item.get('Name'),
                type=EmbyItemType(item.get('Type', 'Movie')),
                path=item.get('Path'),
                overview=item.get('Overview'),
                genres=item.get('Genres', []),
                studios=item.get('Studios', []),
            ))
        
        return items
    
    async def get_item_by_path(self, path: str) -> Optional[EmbyItem]:
        """
        通过路径获取媒体项目
        
        Args:
            path: 文件路径
            
        Returns:
            媒体项目
        """
        params = {
            'Path': path,
            'Recursive': 'true',
            'Limit': 1,
        }
        
        data = await self._request('GET', '/Items', params=params)
        items = data.get('Items', [])
        
        if items:
            item = items[0]
            return EmbyItem(
                id=item.get('Id'),
                name=item.get('Name'),
                type=EmbyItemType(item.get('Type', 'Movie')),
                path=item.get('Path'),
            )
        
        return None
    
    async def get_item_by_id(self, item_id: str) -> Optional[EmbyItem]:
        """
        通过 ID 获取媒体项目
        
        Args:
            item_id: 项目 ID
            
        Returns:
            媒体项目
        """
        data = await self._request('GET', f'/Users/{self.config.user_id}/Items/{item_id}')
        
        if data:
            return EmbyItem(
                id=data.get('Id'),
                name=data.get('Name'),
                type=EmbyItemType(data.get('Type', 'Movie')),
                path=data.get('Path'),
                overview=data.get('Overview'),
                genres=data.get('Genres', []),
                studios=data.get('Studios', []),
                premiere_date=self._parse_date(data.get('PremiereDate')),
                community_rating=data.get('CommunityRating'),
                image_primary=data.get('ImageTags', {}).get('Primary'),
            )
        
        return None
    
    async def update_item(self, item_id: str, metadata: dict) -> bool:
        """
        更新媒体元数据
        
        Args:
            item_id: 项目 ID
            metadata: 元数据
            
        Returns:
            是否成功
        """
        try:
            await self._request('POST', f'/Items/{item_id}', json_data=metadata)
            logger.info(f"Updated Emby item: {item_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update Emby item {item_id}: {e}")
            return False
    
    async def refresh_item(
        self,
        item_id: str,
        recursive: bool = True,
        metadata_refresh: bool = True,
        image_refresh: bool = False,
        replace_all_metadata: bool = False,
    ) -> bool:
        """
        刷新媒体项目
        
        Args:
            item_id: 项目 ID
            recursive: 是否递归
            metadata_refresh: 是否刷新元数据
            image_refresh: 是否刷新图片
            replace_all_metadata: 是否替换所有元数据
            
        Returns:
            是否成功
        """
        params = {
            'Recursive': str(recursive).lower(),
            'MetadataRefreshMode': 'FullRefresh' if metadata_refresh else 'None',
            'ImageRefreshMode': 'FullRefresh' if image_refresh else 'None',
            'ReplaceAllMetadata': str(replace_all_metadata).lower(),
        }
        
        try:
            await self._request('POST', f'/Items/{item_id}/Refresh', params=params)
            logger.info(f"Refreshed Emby item: {item_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh Emby item {item_id}: {e}")
            return False
    
    async def push_scraped_result(
        self,
        item_id: str,
        title: str,
        overview: Optional[str] = None,
        genres: Optional[list[str]] = None,
        actors: Optional[list[dict]] = None,
        studios: Optional[list[str]] = None,
        premiere_date: Optional[str] = None,
        community_rating: Optional[float] = None,
        image_path: Optional[str] = None,
    ) -> bool:
        """
        推送刮削结果到 Emby
        
        Args:
            item_id: 项目 ID
            title: 标题
            overview: 简介
            genres: 标签
            actors: 演员
            studios: 制作商
            premiere_date: 发行日期
            community_rating: 评分
            image_path: 图片路径
            
        Returns:
            是否成功
        """
        metadata = {
            'Name': title,
        }
        
        if overview:
            metadata['Overview'] = overview
        
        if genres:
            metadata['Genres'] = genres
        
        if studios:
            metadata['Studios'] = [{'Name': s} for s in studios]
        
        if premiere_date:
            metadata['PremiereDate'] = premiere_date
        
        if community_rating:
            metadata['CommunityRating'] = community_rating
        
        if actors:
            metadata['People'] = [
                {'Name': a.get('name'), 'Type': 'Actor'}
                for a in actors
            ]
        
        # 更新元数据
        success = await self.update_item(item_id, metadata)
        
        if success and image_path:
            # 上传图片
            await self._upload_image(item_id, image_path)
        
        if success:
            # 刷新项目
            await self.refresh_item(item_id)
        
        return success
    
    async def _upload_image(self, item_id: str, image_path: str) -> bool:
        """
        上传图片
        
        Args:
            item_id: 项目 ID
            image_path: 图片路径
            
        Returns:
            是否成功
        """
        from pathlib import Path
        
        path = Path(image_path)
        if not path.exists():
            logger.warning(f"Image not found: {image_path}")
            return False
        
        url = f"{self.base_url}/Items/{item_id}/Images/Primary"
        
        async with httpx.AsyncClient(
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
        ) as client:
            try:
                with open(path, 'rb') as f:
                    response = await client.post(
                        url,
                        headers={'X-Emby-Token': self.api_key},
                        content=f.read(),
                    )
                    response.raise_for_status()
                    logger.info(f"Uploaded image to Emby: {item_id}")
                    return True
            
            except Exception as e:
                logger.error(f"Failed to upload image: {e}")
                return False
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None
        
        try:
            # Emby 日期格式: 2024-04-19T00:00:00.0000000Z
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            return None
    
    async def get_person_by_name(self, name: str) -> Optional[dict]:
        """
        获取演员信息
        
        Args:
            name: 演员名
            
        Returns:
            演员信息
        """
        params = {
            'SearchTerm': name,
            'IncludeItemTypes': 'Person',
            'Limit': 1,
        }
        
        data = await self._request('GET', '/Items', params=params)
        items = data.get('Items', [])
        
        if items:
            return items[0]
        return None
    
    async def update_person_image(
        self,
        person_id: str,
        image_url: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> bool:
        """
        更新演员头像
        
        Args:
            person_id: 演员 ID
            image_url: 图片 URL
            image_path: 本地图片路径
            
        Returns:
            是否成功
        """
        if image_url:
            # 从 URL 下载并上传
            url = f"{self.base_url}/Items/{person_id}/Images/Primary"
            
            async with httpx.AsyncClient(
                timeout=self.config.timeout,
                verify=self.config.verify_ssl,
            ) as client:
                try:
                    # 下载图片
                    img_response = await client.get(image_url)
                    img_response.raise_for_status()
                    
                    # 上传到 Emby
                    response = await client.post(
                        url,
                        headers={'X-Emby-Token': self.api_key},
                        content=img_response.content,
                    )
                    response.raise_for_status()
                    return True
                
                except Exception as e:
                    logger.error(f"Failed to update person image: {e}")
                    return False
        
        elif image_path:
            return await self._upload_image(person_id, image_path)
        
        return False


async def push_to_emby(
    emby_url: str,
    api_key: str,
    item_id: str,
    metadata: dict,
) -> bool:
    """
    推送刮削结果到 Emby 的便捷函数
    
    Args:
        emby_url: Emby 服务器地址
        api_key: API Key
        item_id: 项目 ID
        metadata: 元数据
        
    Returns:
        是否成功
    """
    config = EmbyConfig(url=emby_url, api_key=api_key)
    client = EmbyClient(config)
    
    return await client.push_scraped_result(item_id, **metadata)
